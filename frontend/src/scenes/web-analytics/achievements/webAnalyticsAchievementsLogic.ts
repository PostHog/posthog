import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    webAnalyticsAchievementsAcknowledgeCelebration,
    webAnalyticsAchievementsOverview,
} from 'products/web_analytics/frontend/generated/api'
import type {
    AchievementDefinitionApi,
    AchievementProgressApi,
    AchievementsListResponseApi,
    PendingCelebrationApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { deriveTrackProgress } from './achievementProgress'
import { isWebAnalyticsAchievementsEnabled } from './gating'
import type { webAnalyticsAchievementsLogicType } from './webAnalyticsAchievementsLogicType'
import { webAnalyticsAchievementsPreferencesLogic } from './webAnalyticsAchievementsPreferencesLogic'

const celebrationKey = (trackKey: string, stage: number): string => `${trackKey}:${stage}`

function sortByCloseness(
    tracks: AchievementDefinitionApi[],
    progressByTrack: Record<string, AchievementProgressApi>
): AchievementDefinitionApi[] {
    return [...tracks]
        .map((track) => ({ track, derived: deriveTrackProgress(track, progressByTrack[track.key]) }))
        .sort((a, b) => {
            if (a.derived.maxed !== b.derived.maxed) {
                return a.derived.maxed ? 1 : -1
            }
            return a.derived.fractionRemaining - b.derived.fractionRemaining
        })
        .map(({ track }) => track)
}

export const webAnalyticsAchievementsLogic = kea<webAnalyticsAchievementsLogicType>([
    path(['scenes', 'web-analytics', 'achievements', 'webAnalyticsAchievementsLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentProjectId'],
            featureFlagLogic,
            ['featureFlags'],
            webAnalyticsAchievementsPreferencesLogic,
            ['achievementsOptOut', 'preferences'],
        ],
    })),
    actions({
        openModal: true,
        closeModal: true,
        acknowledgeCelebration: (trackKey: string, stage: number) => ({ trackKey, stage }),
        markCelebrated: (key: string) => ({ key }),
        triggerConfetti: true,
        enqueueCelebrationConfetti: (trackKeys: string[]) => ({ trackKeys }),
        toggleTrackExpanded: (trackKey: string) => ({ trackKey }),
    }),
    loaders(({ values }) => ({
        achievements: [
            null as AchievementsListResponseApi | null,
            {
                loadAchievements: async () => {
                    return await webAnalyticsAchievementsOverview(String(values.currentProjectId))
                },
            },
        ],
    })),
    reducers({
        modalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        celebratedKeys: [
            [] as string[],
            {
                markCelebrated: (state, { key }) => (state.includes(key) ? state : [...state, key]),
            },
        ],
        confettiNonce: [
            0,
            {
                triggerConfetti: (state) => state + 1,
            },
        ],
        // Tracks with a fresh unlock waiting to be celebrated the next time the user opens the modal.
        // Populated on load, drained when the modal closes so a burst fires once per batch, not on every passive visit.
        celebrationConfettiQueue: [
            [] as string[],
            {
                enqueueCelebrationConfetti: (state, { trackKeys }) => Array.from(new Set([...state, ...trackKeys])),
                closeModal: () => [],
            },
        ],
        expandedTracks: [
            [] as string[],
            {
                toggleTrackExpanded: (state, { trackKey }) =>
                    state.includes(trackKey) ? state.filter((key) => key !== trackKey) : [...state, trackKey],
                closeModal: () => [],
            },
        ],
    }),
    selectors({
        definitions: [
            (s) => [s.achievements],
            (achievements): AchievementDefinitionApi[] => achievements?.definitions ?? [],
        ],
        userProgress: [
            (s) => [s.achievements],
            (achievements): AchievementProgressApi[] => achievements?.user_progress ?? [],
        ],
        teamProgress: [
            (s) => [s.achievements],
            (achievements): AchievementProgressApi[] => achievements?.team_progress ?? [],
        ],
        pendingCelebrations: [
            (s) => [s.achievements],
            (achievements): PendingCelebrationApi[] => achievements?.pending_celebrations ?? [],
        ],
        uncelebratedPending: [
            (s) => [s.pendingCelebrations, s.celebratedKeys],
            (pending, celebrated): PendingCelebrationApi[] =>
                pending.filter((entry) => !celebrated.includes(celebrationKey(entry.track_key, entry.stage))),
        ],
        progressByTrack: [
            (s) => [s.userProgress, s.teamProgress],
            (userProgress, teamProgress): Record<string, AchievementProgressApi> => {
                const byTrack: Record<string, AchievementProgressApi> = {}
                for (const row of [...userProgress, ...teamProgress]) {
                    byTrack[row.track_key] = row
                }
                return byTrack
            },
        ],
        sortedUserTracks: [
            (s) => [s.definitions, s.progressByTrack],
            (definitions, progressByTrack): AchievementDefinitionApi[] =>
                sortByCloseness(
                    definitions.filter((track) => track.scope === 'user'),
                    progressByTrack
                ),
        ],
        sortedTeamTracks: [
            (s) => [s.definitions, s.progressByTrack],
            (definitions, progressByTrack): AchievementDefinitionApi[] =>
                sortByCloseness(
                    definitions.filter((track) => track.scope === 'team'),
                    progressByTrack
                ),
        ],
        pendingTrackKeys: [(s) => [s.celebrationConfettiQueue], (queue): Set<string> => new Set(queue)],
        unlockedStages: [
            (s) => [s.definitions, s.progressByTrack],
            (definitions, progressByTrack): number =>
                definitions.reduce((sum, track) => sum + (progressByTrack[track.key]?.current_stage ?? 0), 0),
        ],
        totalStages: [
            (s) => [s.definitions],
            (definitions): number => definitions.reduce((sum, track) => sum + track.stages.length, 0),
        ],
    }),
    listeners(({ values, actions }) => ({
        openModal: () => {
            posthog.capture('web_analytics_achievements_opened')
            // Celebrate now that the user has deliberately opened the modal, rather than on a passive dashboard visit.
            if (values.celebrationConfettiQueue.length > 0) {
                actions.triggerConfetti()
            }
            actions.loadAchievements()
        },
        loadAchievementsSuccess: () => {
            const pending = values.uncelebratedPending
            if (pending.length === 0) {
                return
            }
            if (pending.length === 1) {
                const entry = pending[0]
                const track = values.definitions.find((t) => t.key === entry.track_key)
                lemonToast.success(
                    `Achievement unlocked — ${track?.display_name ?? entry.track_key}: ${entry.stage_name}`,
                    {
                        button: {
                            label: 'View',
                            action: () => actions.openModal(),
                        },
                    }
                )
            } else {
                lemonToast.success(`You've unlocked ${pending.length} web analytics achievements`, {
                    button: {
                        label: 'View',
                        action: () => actions.openModal(),
                    },
                })
            }
            // Queue a celebratory burst for the next deliberate modal open instead of firing it on this passive visit.
            actions.enqueueCelebrationConfetti(pending.map((entry) => entry.track_key))
            if (values.modalOpen) {
                actions.triggerConfetti()
            }
            pending.forEach((entry) => {
                actions.acknowledgeCelebration(entry.track_key, entry.stage)
            })
        },
        acknowledgeCelebration: async ({ trackKey, stage }) => {
            const track = values.definitions.find((t) => t.key === trackKey)
            posthog.capture('web_analytics_achievement_unlocked', {
                track_key: trackKey,
                stage,
                stage_name: track?.stages[stage - 1]?.name,
                scope: track?.scope,
            })
            actions.markCelebrated(celebrationKey(trackKey, stage))
            try {
                await webAnalyticsAchievementsAcknowledgeCelebration(String(values.currentProjectId), {
                    track_key: trackKey,
                    stage,
                })
            } catch (error) {
                posthog.captureException(error)
            }
        },
        [webAnalyticsAchievementsPreferencesLogic.actionTypes.loadPreferencesSuccess]: () => {
            if (isWebAnalyticsAchievementsEnabled(values.featureFlags, values.achievementsOptOut)) {
                actions.loadAchievements()
            }
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.preferences && isWebAnalyticsAchievementsEnabled(values.featureFlags, values.achievementsOptOut)) {
            actions.loadAchievements()
        }
    }),
])
