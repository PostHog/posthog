import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
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
    reviewHogSettingsPartialUpdate,
    reviewHogSettingsRetrieve,
    reviewHogValidatorsList,
    reviewHogValidatorsPartialUpdate,
} from 'products/review_hog/frontend/generated/api'
import type {
    PatchedReviewUserSettingsApi,
    ReviewBlindSpotsConfigApi,
    ReviewPerspectiveConfigApi,
    ReviewRecentReviewApi,
    ReviewUserSettingsApi,
    ReviewValidatorConfigApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import type { reviewHogSettingsLogicType } from './reviewHogSettingsLogicType'

export type ReviewSkillKind = 'perspective' | 'blind_spots' | 'validator'

/** The skill a "View skill" click opens in the read-only drawer. */
export interface ViewedSkill {
    title: string
    body: string
    /** The `review-hog-*` skill name, for the drawer's link to the skill's editor page. */
    skillName: string
}

const SKILL_AUTHOR_TASKS: Record<ReviewSkillKind, { title: string; prompt: string }> = {
    perspective: {
        title: 'Create a ReviewHog perspective',
        prompt: `I'd like to create a custom ReviewHog review perspective for this PostHog project. ReviewHog is the automated PR reviewer: each enabled perspective is a team skill whose body instructs one specialist review pass that reads every PR chunk in parallel with the other perspectives.

First, ground yourself: list the team's skills named \`review-hog-perspective-*\` (PostHog MCP skill tools) and read a canonical one (for example \`review-hog-perspective-logic-correctness\`) so you understand the shape and avoid overlapping an existing lens.

Then ask me what my perspective should focus on, and offer a few concrete directions the current set doesn't already cover.

Once I pick, author the skill end to end: create a team skill named \`review-hog-perspective-<short-slug>\` (category \`review_hog\`) whose body is a focused instruction set for that review pass — what to hunt for, what to ignore, and what a publishable finding looks like.

When it's created, remind me to enable it under Inbox → Code review → Perspectives (it shows up disabled for me until I toggle it on).`,
    },
    blind_spots: {
        title: 'Create a ReviewHog blind-spot check',
        prompt: `I'd like to create a custom ReviewHog blind-spot check for this PostHog project. ReviewHog is the automated PR reviewer: after the review perspectives finish a chunk, one blind-spot skill runs a final sweep over that chunk — it sees what the perspectives found and hunts for real issues they all missed.

First, ground yourself: read the canonical skill \`review-hog-blind-spots-general\` (PostHog MCP skill tools) so you understand the shape, and list any other \`review-hog-blind-spots-*\` skills on the team.

Then ask me what my sweep should emphasize, and offer a few concrete directions.

Once I pick, author the skill end to end: create a team skill named \`review-hog-blind-spots-<short-slug>\` (category \`review_hog\`) whose body instructs that final sweep — how to use the covered findings, where to dig, and what a publishable finding looks like.

When it's created, remind me to select it under Inbox → Code review → Blind-spot check (only one runs at a time; selecting it swaps out the current one for my reviews only).`,
    },
    validator: {
        title: 'Create ReviewHog validation criteria',
        prompt: `I'd like to create custom ReviewHog validation criteria for this PostHog project. ReviewHog is the automated PR reviewer: every candidate finding is judged by one validator skill against a quality bar, and only findings that pass get published to the pull request.

First, ground yourself: read the canonical skill \`review-hog-validation-criteria\` (PostHog MCP skill tools) so you understand the shape and the current bar.

Then ask me how my bar should differ — stricter, more lenient, or weighted toward specific concerns — and offer a few concrete directions.

Once I pick, author the skill end to end: create a team skill named \`review-hog-validation-<short-slug>\` (category \`review_hog\`) whose body defines the bar: what makes a finding real, actionable, and worth a reviewer's attention, and what should be rejected as noise.

When it's created, remind me to select it under Inbox → Code review → Validation criteria (only one applies at a time; selecting it swaps out the current one for my reviews only).`,
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

    listeners(({ actions, values }) => ({
        loadAll: () => {
            actions.loadSettings()
            actions.loadPerspectives()
            actions.loadBlindSpots()
            actions.loadValidators()
            actions.loadRecentReviews()
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
