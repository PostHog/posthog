import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import {
    SessionRecordingTriggerGroup,
    SessionRecordingTriggerGroupsConfig,
} from '~/lib/components/IngestionControls/types'

import type { replayTriggersV2LogicType } from './replayTriggersV2LogicType'

export const replayTriggersV2Logic = kea<replayTriggersV2LogicType>([
    path(['lib', 'components', 'IngestionControls', 'triggers', 'triggerGroups', 'replayTriggersV2Logic']),
    connect({
        values: [teamLogic, ['currentTeam']],
        actions: [teamLogic, ['updateCurrentTeam']],
    }),
    actions({
        setTriggerGroupsConfig: (config: SessionRecordingTriggerGroupsConfig | null) => ({ config }),
        addTriggerGroup: (group: SessionRecordingTriggerGroup) => ({ group }),
        deleteTriggerGroup: (id: string) => ({ id }),
        updateTriggerGroup: (id: string, updates: Partial<SessionRecordingTriggerGroup>) => ({ id, updates }),
        setIsAddingGroup: (isAdding: boolean) => ({ isAdding }),
        setEditingGroupId: (id: string | null) => ({ id }),
    }),
    loaders(({ values }) => ({
        _loadingState: [
            false,
            {
                saveConfig: async () => {
                    // Save to backend via teamLogic
                    await teamLogic.asyncActions.updateCurrentTeam({
                        session_recording_trigger_groups: values.triggerGroupsConfig,
                    })
                    return true
                },
            },
        ],
    })),
    reducers({
        triggerGroupsConfig: [
            null as SessionRecordingTriggerGroupsConfig | null,
            {
                setTriggerGroupsConfig: (_, { config }) => config,
                addTriggerGroup: (state, { group }) => {
                    if (!state) {
                        // Initialize with new group
                        return {
                            version: 2 as const,
                            groups: [group],
                        }
                    }
                    return {
                        ...state,
                        groups: [...state.groups, group],
                    }
                },
                deleteTriggerGroup: (state, { id }) => {
                    if (!state) {
                        return state
                    }
                    return {
                        ...state,
                        groups: state.groups.filter((g) => g.id !== id),
                    }
                },
                updateTriggerGroup: (state, { id, updates }) => {
                    if (!state) {
                        return state
                    }
                    return {
                        ...state,
                        groups: state.groups.map((g) => (g.id === id ? { ...g, ...updates } : g)),
                    }
                },
            },
        ],
        isAddingGroup: [
            false,
            {
                setIsAddingGroup: (_, { isAdding }) => isAdding,
                addTriggerGroup: () => false, // Close form after adding
            },
        ],
        editingGroupId: [
            null as string | null,
            {
                setEditingGroupId: (_, { id }) => id,
                updateTriggerGroup: () => null, // Close form after updating
            },
        ],
    }),
    selectors({
        triggerGroups: [
            (s) => [s.triggerGroupsConfig],
            (config): SessionRecordingTriggerGroup[] => {
                return config?.groups || []
            },
        ],
        hasV2Config: [
            (s) => [s.triggerGroupsConfig],
            (config): boolean => {
                return config !== null && config.version === 2
            },
        ],
    }),
    listeners(({ asyncActions }) => ({
        addTriggerGroup: async () => {
            // Auto-save after adding
            await asyncActions.saveConfig()
        },
        deleteTriggerGroup: async () => {
            // Auto-save after deleting
            await asyncActions.saveConfig()
        },
        updateTriggerGroup: async () => {
            // Auto-save after updating
            await asyncActions.saveConfig()
        },
        saveConfigSuccess: () => {
            lemonToast.success('Trigger group saved')
        },
        saveConfigFailure: ({ error }) => {
            lemonToast.error('Failed to save trigger group. Please try again.')
            console.error('Error saving trigger group:', error)
        },
    })),
    // Load config from currentTeam on mount
    afterMount(({ actions, values }) => {
        if (values.currentTeam?.session_recording_trigger_groups) {
            actions.setTriggerGroupsConfig(values.currentTeam.session_recording_trigger_groups)
        }
    }),
])
