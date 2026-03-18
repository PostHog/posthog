import { actions, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import {
    SessionRecordingTriggerGroup,
    SessionRecordingTriggerGroupsConfig,
} from '~/lib/components/IngestionControls/types'

import type { replayTriggersV2LogicType } from './replayTriggersV2LogicType'

export const replayTriggersV2Logic = kea<replayTriggersV2LogicType>([
    path(['scenes', 'settings', 'environment', 'replayTriggers', 'replayTriggersV2Logic']),
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    actions({
        // TODO: Implement actions for CRUD operations
        addTriggerGroup: (group: SessionRecordingTriggerGroup) => ({ group }),
        updateTriggerGroup: (id: string, updates: Partial<SessionRecordingTriggerGroup>) => ({ id, updates }),
        deleteTriggerGroup: (id: string) => ({ id }),
        reorderTriggerGroups: (groupIds: string[]) => ({ groupIds }),
        setGroupEvaluationMode: (mode: 'first_match' | 'highest_priority') => ({ mode }),
        setFallbackSampleRate: (rate: number | undefined) => ({ rate }),
        saveTriggerGroups: true,
    }),
    loaders(({ values }) => ({
        triggerGroupsConfig: [
            null as SessionRecordingTriggerGroupsConfig | null,
            {
                // TODO: Implement actual loading from API
                loadTriggerGroupsConfig: async () => {
                    // For now, return from currentTeam
                    return values.currentTeam?.session_recording_trigger_groups || null
                },
                // TODO: Implement save functionality
                saveTriggerGroups: async () => {
                    // Will call teamLogic.actions.updateCurrentTeam() with updated config
                    return values.triggerGroupsConfig
                },
            },
        ],
    })),
    // TODO: Add reducers for CRUD operations in next PR
    selectors({
        triggerGroups: [
            (s) => [s.triggerGroupsConfig],
            (config): SessionRecordingTriggerGroup[] => {
                return config?.groups || []
            },
        ],
        groupEvaluationMode: [
            (s) => [s.triggerGroupsConfig],
            (config): 'first_match' | 'highest_priority' => {
                return config?.groupEvaluationMode || 'first_match'
            },
        ],
        fallbackSampleRate: [
            (s) => [s.triggerGroupsConfig],
            (config): number | undefined => {
                return config?.fallbackSampleRate
            },
        ],
        hasV2Config: [
            (s) => [s.triggerGroupsConfig],
            (config): boolean => {
                return config !== null && config.version === 2
            },
        ],
    }),
])
