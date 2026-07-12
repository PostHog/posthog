import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    webAnalyticsAchievementsAcknowledgeCelebration,
    webAnalyticsAchievementsOverview,
    webAnalyticsAchievementsRecordInteraction,
} from 'products/web_analytics/frontend/generated/api'
import {
    type AchievementDefinitionApi,
    type AchievementProgressApi,
    type AchievementsListResponseApi,
    InteractionKindEnumApi,
    type PendingCelebrationApi,
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
        recordInteraction: (kind: InteractionKindEnumApi) => ({ kind }),
        markCelebrated: (key: string) => ({ key }),
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
        pendingTrackKeys: [
            (s) => [s.uncelebratedPending],
            (pending): Set<string> => new Set(pending.map((entry) => entry.track_key)),
        ],
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
        recordInteraction: async ({ kind }) => {
            if (!isWebAnalyticsAchievementsEnabled(values.featureFlags, values.achievementsOptOut)) {
                return
            }
            if (values.currentProjectId === undefined || values.currentProjectId === null) {
                return
            }
            try {
                await webAnalyticsAchievementsRecordInteraction(String(values.currentProjectId), {
                    interaction_kind: kind,
                })
                actions.loadAchievements()
            } catch {
                // best-effort gamification signal: never surface recording failures
            }
        },
        // Dashboard interactions count toward achievements. These reports fire only from web
        // analytics UI, where this logic is mounted via the scene menu bar.
        [eventUsageLogic.actionTypes.reportWebAnalyticsFilterApplied]: () => {
            actions.recordInteraction(InteractionKindEnumApi.Data)
        },
        [eventUsageLogic.actionTypes.reportWebAnalyticsFilterRemoved]: () => {
            actions.recordInteraction(InteractionKindEnumApi.Data)
        },
        [eventUsageLogic.actionTypes.reportWebAnalyticsDateRangeChanged]: () => {
            actions.recordInteraction(InteractionKindEnumApi.Data)
        },
        [eventUsageLogic.actionTypes.reportWebAnalyticsCompareToggled]: () => {
            actions.recordInteraction(InteractionKindEnumApi.Data)
        },
        [eventUsageLogic.actionTypes.reportWebAnalyticsPathCleaningToggled]: () => {
            actions.recordInteraction(InteractionKindEnumApi.Data)
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.preferences && isWebAnalyticsAchievementsEnabled(values.featureFlags, values.achievementsOptOut)) {
            actions.loadAchievements()
        }
    }),
])
