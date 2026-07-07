import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { OriginProduct } from 'products/posthog_ai/frontend/types/taskTypes'
import {
    reviewHogBlindSpotsList,
    reviewHogBlindSpotsPartialUpdate,
    reviewHogPerspectivesList,
    reviewHogPerspectivesPartialUpdate,
    reviewHogReviewsList,
    reviewHogReviewsPerspectiveStatsRetrieve,
    reviewHogReviewsRetrieve,
    reviewHogSettingsPartialUpdate,
    reviewHogSettingsRetrieve,
    reviewHogValidatorsList,
    reviewHogValidatorsPartialUpdate,
} from 'products/review_hog/frontend/generated/api'
import type {
    PatchedReviewUserSettingsApi,
    ReviewBlindSpotsConfigApi,
    ReviewDetailApi,
    ReviewFindingApi,
    ReviewIssuePriorityEnumApi,
    ReviewPerspectiveConfigApi,
    ReviewPerspectiveStatsApi,
    ReviewRecentReviewApi,
    ReviewUserSettingsApi,
    ReviewValidatorConfigApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import type { reviewHogSettingsLogicType } from './reviewHogSettingsLogicType'

export type ReviewSkillKind = 'perspective' | 'blind_spots' | 'validator'

export type ReviewDrawerTab = 'published' | 'below_threshold' | 'dismissed' | 'chunks' | 'review'

export const REVIEW_PRIORITY_RANK: Record<ReviewIssuePriorityEnumApi, number> = {
    consider: 0,
    should_fix: 1,
    must_fix: 2,
}

// While a review is running, the list refreshes on this cadence so the stage/progress row is live.
const IN_PROGRESS_POLL_INTERVAL_MS = 10_000

/** The detail's valid findings split by the user's urgency threshold: on the PR vs. kept back. */
export interface ReviewFindingsSplit {
    published: ReviewFindingApi[]
    belowThreshold: ReviewFindingApi[]
}

/** How many surviving findings each review skill contributed, largest contributor first. */
export interface PerspectiveScore {
    skillName: string
    count: number
}

/** The skill a "View skill" click opens in the read-only drawer. */
export interface ViewedSkill {
    title: string
    body: string
    /** The `review-hog-*` skill name, for the drawer's link to the skill's editor page. */
    skillName: string
}

// Thin scout-style kickoff pointers (mirrors SCOUT_AUTHOR_PROMPT): the actual authoring guide —
// pipeline context, naming contract, per-kind body shape, activation steps — lives in the
// `review-hog-authoring` team skill (canonical source: products/review_hog/skills/), synced per
// team like the perspectives. Keep knowledge there, not here.
const SKILL_AUTHOR_TASKS: Record<ReviewSkillKind, { title: string; prompt: string }> = {
    perspective: {
        title: 'Create a ReviewHog perspective',
        prompt: `I'd like to create a custom ReviewHog review perspective for this PostHog project.

Use the review-hog-authoring skill from the PostHog MCP to guide creating it — follow its review-perspective path.

Ground yourself per that skill first, then ask me what my perspective should focus on and offer a few concrete directions the current set doesn't already cover. Once I pick, author the skill end to end and tell me how to switch it on.

If the review-hog-authoring skill is unavailable, fall back to the PostHog MCP skill tools directly: list the team's review-hog-perspective-* skills and read a canonical one to learn the shape before authoring.`,
    },
    blind_spots: {
        title: 'Create a ReviewHog blind-spot check',
        prompt: `I'd like to create a custom ReviewHog blind-spot check for this PostHog project.

Use the review-hog-authoring skill from the PostHog MCP to guide creating it — follow its blind-spot-check path.

Ground yourself per that skill first, then ask me what my sweep should emphasize and offer a few concrete directions. Once I pick, author the skill end to end and tell me how to switch it on.

If the review-hog-authoring skill is unavailable, fall back to the PostHog MCP skill tools directly: read the canonical review-hog-blind-spots-general skill to learn the shape before authoring.`,
    },
    validator: {
        title: 'Create ReviewHog validation criteria',
        prompt: `I'd like to create custom ReviewHog validation criteria for this PostHog project.

Use the review-hog-authoring skill from the PostHog MCP to guide creating it — follow its validation-criteria path.

Ground yourself per that skill first, then ask me how my bar should differ — stricter, more lenient, or weighted toward specific concerns — and offer a few concrete directions. Once I pick, author the skill end to end and tell me how to switch it on.

If the review-hog-authoring skill is unavailable, fall back to the PostHog MCP skill tools directly: read the canonical review-hog-validation-criteria skill to learn the shape before authoring.`,
    },
}

function currentProjectId(): string {
    return String(teamLogic.values.currentTeamId)
}

/**
 * State for the Inbox "Code review" tab: the user's ReviewHog settings (triggers + urgency
 * threshold) and the three skill lists (perspectives / blind-spot check / validation criteria)
 * with their per-user enablement. Cardinality rules mirror the backend: perspectives keep a
 * min-1 floor, blind spots and validators are exactly-one-active (deactivation is blocked,
 * you switch by selecting another). "Create your own …" kicks off an authoring agent task,
 * mirroring the Inbox "Make a scout" flow.
 */
export const reviewHogSettingsLogic = kea<reviewHogSettingsLogicType>([
    path(['scenes', 'inbox', 'logics', 'reviewHogSettingsLogic']),

    actions({
        // Fires the four initial loads — also the retry entry point after a failed load.
        loadAll: true,
        togglePerspective: (skillName: string, enabled: boolean) => ({ skillName, enabled }),
        patchPerspectiveLocally: (skillName: string, enabled: boolean) => ({ skillName, enabled }),
        selectBlindSpots: (skillName: string) => ({ skillName }),
        selectValidator: (skillName: string) => ({ skillName }),
        // The active card's switch can't be turned off — exactly one stays active per kind.
        blockSingleActiveDeactivation: (kindLabel: string) => ({ kindLabel }),
        setSkillSaving: (skillName: string, saving: boolean) => ({ skillName, saving }),
        viewSkill: (skill: ViewedSkill) => ({ skill }),
        closeSkillDrawer: true,
        openReviewDetail: (review: ReviewRecentReviewApi) => ({ review }),
        closeReviewDrawer: true,
        setReviewDrawerTab: (tab: ReviewDrawerTab) => ({ tab }),
        toggleReviewRowExpanded: (reviewId: string) => ({ reviewId }),
        startSkillAuthorTask: (kind: ReviewSkillKind) => ({ kind }),
        startSkillAuthorTaskFinished: true,
    }),

    loaders(() => ({
        settings: [
            null as ReviewUserSettingsApi | null,
            {
                loadSettings: async () => await reviewHogSettingsRetrieve(currentProjectId()),
                updateSettings: async (patch: PatchedReviewUserSettingsApi, breakpoint) => {
                    const response = await reviewHogSettingsPartialUpdate(currentProjectId(), patch)
                    // A newer update is already in flight — drop this now-stale response.
                    breakpoint()
                    return response
                },
            },
        ],
        perspectives: [
            null as ReviewPerspectiveConfigApi[] | null,
            {
                loadPerspectives: async () => await reviewHogPerspectivesList(currentProjectId()),
            },
        ],
        blindSpots: [
            null as ReviewBlindSpotsConfigApi[] | null,
            {
                loadBlindSpots: async () => await reviewHogBlindSpotsList(currentProjectId()),
            },
        ],
        validators: [
            null as ReviewValidatorConfigApi[] | null,
            {
                loadValidators: async () => await reviewHogValidatorsList(currentProjectId()),
            },
        ],
        recentReviews: [
            null as ReviewRecentReviewApi[] | null,
            {
                loadRecentReviews: async () => await reviewHogReviewsList(currentProjectId()),
            },
        ],
        reviewDetail: [
            null as ReviewDetailApi | null,
            {
                loadReviewDetail: async (reviewId: string) =>
                    await reviewHogReviewsRetrieve(currentProjectId(), reviewId),
            },
        ],
        perspectiveStats: [
            null as ReviewPerspectiveStatsApi | null,
            {
                loadPerspectiveStats: async () => await reviewHogReviewsPerspectiveStatsRetrieve(currentProjectId()),
            },
        ],
    })),

    reducers({
        settings: {
            // Optimistic: the switches/slider reflect the change immediately; a failure listener
            // reloads to reconcile.
            updateSettings: (state: ReviewUserSettingsApi | null, patch: PatchedReviewUserSettingsApi) =>
                state ? { ...state, ...patch } : state,
        },
        perspectives: {
            patchPerspectiveLocally: (state: ReviewPerspectiveConfigApi[] | null, { skillName, enabled }) =>
                state?.map((p) => (p.skill_name === skillName ? { ...p, enabled } : p)) ?? state,
        },
        blindSpots: {
            selectBlindSpots: (state: ReviewBlindSpotsConfigApi[] | null, { skillName }) =>
                state?.map((s) => ({ ...s, active: s.skill_name === skillName })) ?? state,
        },
        validators: {
            selectValidator: (state: ReviewValidatorConfigApi[] | null, { skillName }) =>
                state?.map((s) => ({ ...s, active: s.skill_name === skillName })) ?? state,
        },
        savingSkillNames: [
            [] as string[],
            {
                setSkillSaving: (state, { skillName, saving }) =>
                    saving ? [...state, skillName] : state.filter((name) => name !== skillName),
            },
        ],
        viewedSkill: [
            // Kept through close so the drawer doesn't blank mid-animation; `skillDrawerOpen` gates visibility.
            null as ViewedSkill | null,
            {
                viewSkill: (_, { skill }) => skill,
            },
        ],
        skillDrawerOpen: [
            false,
            {
                viewSkill: () => true,
                closeSkillDrawer: () => false,
            },
        ],
        // The clicked list row: the drawer header renders from it instantly while the detail loads.
        openedReview: [
            null as ReviewRecentReviewApi | null,
            {
                openReviewDetail: (_, { review }) => review,
            },
        ],
        reviewDetail: {
            // Clear the previous review's detail so opening another row never flashes stale findings.
            openReviewDetail: () => null,
        },
        reviewDrawerOpen: [
            false,
            {
                openReviewDetail: () => true,
                closeReviewDrawer: () => false,
            },
        ],
        reviewDrawerTab: [
            'published' as ReviewDrawerTab,
            {
                setReviewDrawerTab: (_, { tab }) => tab,
                openReviewDetail: () => 'published' as ReviewDrawerTab,
            },
        ],
        expandedReviewIds: [
            [] as string[],
            {
                toggleReviewRowExpanded: (state, { reviewId }) =>
                    state.includes(reviewId) ? state.filter((id) => id !== reviewId) : [...state, reviewId],
            },
        ],
        initialLoadFailed: [
            false,
            {
                loadAll: () => false,
                loadSettingsFailure: () => true,
                loadPerspectivesFailure: () => true,
                loadBlindSpotsFailure: () => true,
                loadValidatorsFailure: () => true,
            },
        ],
        creatingSkillKind: [
            // Guards the "Create your own …" buttons against double-submission while the task spins up.
            null as ReviewSkillKind | null,
            {
                startSkillAuthorTask: (_, { kind }) => kind,
                startSkillAuthorTaskFinished: () => null,
            },
        ],
    }),

    selectors({
        // Splits the detail's valid findings by the CURRENT threshold — a close-enough proxy for
        // what the run published (the run's own threshold snapshot isn't stored).
        reviewFindingsSplit: [
            (s) => [s.reviewDetail, s.settings],
            (reviewDetail, settings): ReviewFindingsSplit | null => {
                if (!reviewDetail) {
                    return null
                }
                const thresholdRank = REVIEW_PRIORITY_RANK[settings?.urgency_threshold ?? 'should_fix']
                return {
                    published: reviewDetail.findings.filter(
                        (f) => REVIEW_PRIORITY_RANK[f.effective_priority] >= thresholdRank
                    ),
                    belowThreshold: reviewDetail.findings.filter(
                        (f) => REVIEW_PRIORITY_RANK[f.effective_priority] < thresholdRank
                    ),
                }
            },
        ],
        perspectiveScoreboard: [
            (s) => [s.reviewDetail],
            (reviewDetail): PerspectiveScore[] | null => {
                if (!reviewDetail?.findings.length) {
                    return null
                }
                const counts = new Map<string, number>()
                for (const finding of reviewDetail.findings) {
                    const skillName = finding.source_perspective ?? 'unknown'
                    counts.set(skillName, (counts.get(skillName) ?? 0) + 1)
                }
                return Array.from(counts, ([skillName, count]) => ({ skillName, count })).sort(
                    (a, b) => b.count - a.count
                )
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        // Poll while any review is running so the stage row moves; the disposable auto-pauses on
        // hidden tabs and is torn down on unmount.
        loadRecentReviewsSuccess: () => {
            if (values.recentReviews?.some((review) => review.in_progress)) {
                cache.disposables.add(() => {
                    const pollTimer = window.setInterval(
                        () => actions.loadRecentReviews(),
                        IN_PROGRESS_POLL_INTERVAL_MS
                    )
                    return () => clearInterval(pollTimer)
                }, 'inProgressPoll')
            } else {
                cache.disposables.dispose('inProgressPoll')
            }
        },
        loadAll: () => {
            actions.loadSettings()
            actions.loadPerspectives()
            actions.loadBlindSpots()
            actions.loadValidators()
            actions.loadRecentReviews()
            actions.loadPerspectiveStats()
        },
        updateSettingsFailure: () => {
            // The global loaders toast already surfaced the error; just reconcile the optimistic state.
            actions.loadSettings()
        },
        togglePerspective: async ({ skillName, enabled }) => {
            // Min-1 floor, mirrored from the backend so the block is instant (the server still 400s).
            const enabledCount = values.perspectives?.filter((p) => p.enabled).length ?? 0
            if (!enabled && enabledCount <= 1) {
                lemonToast.info('Keep at least one perspective enabled')
                return
            }
            actions.patchPerspectiveLocally(skillName, enabled)
            actions.setSkillSaving(skillName, true)
            try {
                await reviewHogPerspectivesPartialUpdate(currentProjectId(), skillName, { enabled })
            } catch (error: any) {
                // `data?.[0]`: DRF renders bare-string ValidationErrors (e.g. the min-1 floor) as a list.
                lemonToast.error(
                    error?.detail || error?.data?.[0] || error?.message || 'Failed to update the perspective'
                )
                actions.loadPerspectives()
            } finally {
                actions.setSkillSaving(skillName, false)
            }
        },
        selectBlindSpots: async ({ skillName }) => {
            actions.setSkillSaving(skillName, true)
            try {
                await reviewHogBlindSpotsPartialUpdate(currentProjectId(), skillName, { active: true })
            } catch (error: any) {
                lemonToast.error(
                    error?.detail || error?.data?.[0] || error?.message || 'Failed to select the blind-spot check'
                )
                actions.loadBlindSpots()
            } finally {
                actions.setSkillSaving(skillName, false)
            }
        },
        selectValidator: async ({ skillName }) => {
            actions.setSkillSaving(skillName, true)
            try {
                await reviewHogValidatorsPartialUpdate(currentProjectId(), skillName, { active: true })
            } catch (error: any) {
                lemonToast.error(
                    error?.detail || error?.data?.[0] || error?.message || 'Failed to select the validation criteria'
                )
                actions.loadValidators()
            } finally {
                actions.setSkillSaving(skillName, false)
            }
        },
        blockSingleActiveDeactivation: ({ kindLabel }) => {
            lemonToast.info(`One ${kindLabel} always runs — switch by selecting another one`)
        },
        openReviewDetail: ({ review }) => {
            actions.loadReviewDetail(review.id)
        },
        startSkillAuthorTask: async ({ kind }) => {
            // Task-kickoff mirroring the Inbox "Make a scout" flow: create an agent task from a
            // templated authoring prompt, then navigate to it. Not a live chat.
            const { title, prompt } = SKILL_AUTHOR_TASKS[kind]
            try {
                let repository: string | undefined
                try {
                    const { repositories } = await api.tasks.repositories()
                    repository = repositories[0]
                } catch {
                    repository = undefined
                }
                const task = await api.tasks.create({
                    title,
                    description: prompt,
                    origin_product: OriginProduct.USER_CREATED,
                    repository,
                })
                router.actions.push(urls.taskDetail(task.id))
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || `Failed to start "${title}"`)
            } finally {
                actions.startSkillAuthorTaskFinished()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadAll()
    }),
])
