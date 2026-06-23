import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

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

import { isWebAnalyticsAchievementsEnabled } from './gating'
import type { webAnalyticsAchievementsLogicType } from './webAnalyticsAchievementsLogicType'

const celebrationKey = (trackKey: string, stage: number): string => `${trackKey}:${stage}`

export const webAnalyticsAchievementsLogic = kea<webAnalyticsAchievementsLogicType>([
    path(['scenes', 'web-analytics', 'achievements', 'webAnalyticsAchievementsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        openModal: true,
        closeModal: true,
        acknowledgeCelebration: (trackKey: string, stage: number) => ({ trackKey, stage }),
        markCelebrated: (key: string) => ({ key }),
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
    }),
    listeners(({ values, actions }) => ({
        acknowledgeCelebration: async ({ trackKey, stage }) => {
            actions.markCelebrated(celebrationKey(trackKey, stage))
            try {
                await webAnalyticsAchievementsAcknowledgeCelebration(String(values.currentProjectId), {
                    track_key: trackKey,
                    stage,
                })
            } catch {}
        },
    })),
    afterMount(({ actions, values }) => {
        if (isWebAnalyticsAchievementsEnabled(values.featureFlags)) {
            actions.loadAchievements()
        }
    }),
])
