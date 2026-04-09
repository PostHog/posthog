import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { uuid } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import {
    EventTriggerConfig,
    LinkedFeatureFlag,
    SessionRecordingTriggerGroup,
    SessionRecordingTriggerGroupsConfig,
    UrlTriggerConfig,
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
        addMultipleTriggerGroups: (groups: SessionRecordingTriggerGroup[]) => ({ groups }),
        deleteTriggerGroup: (id: string) => ({ id }),
        updateTriggerGroup: (id: string, updates: Partial<SessionRecordingTriggerGroup>) => ({ id, updates }),
        setIsAddingGroup: (isAdding: boolean) => ({ isAdding }),
        setEditingGroupId: (id: string | null) => ({ id }),
        setDeleteModalGroupId: (id: string | null) => ({ id }),
        showCreateFromLegacyModal: true,
        hideCreateFromLegacyModal: true,
        confirmCreateFromLegacy: true,
    }),
    loaders(({ values, actions }) => ({
        _savingState: [
            null as boolean | null,
            {
                saveConfig: async () => {
                    // Save to backend via teamLogic
                    await teamLogic.asyncActions.updateCurrentTeam({
                        session_recording_trigger_groups: values.triggerGroupsConfig,
                    })
                    return true
                },
                confirmCreateFromLegacy: async () => {
                    const groups = values.previewLegacyGroups
                    if (groups.length === 0) {
                        return false
                    }

                    // Add all groups
                    actions.addMultipleTriggerGroups(groups)
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
                addMultipleTriggerGroups: (state, { groups }) => {
                    if (!state) {
                        return {
                            version: 2 as const,
                            groups,
                        }
                    }
                    return {
                        ...state,
                        groups: [...state.groups, ...groups],
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
        showLegacyModal: [
            false,
            {
                showCreateFromLegacyModal: () => true,
                hideCreateFromLegacyModal: () => false,
                confirmCreateFromLegacySuccess: () => false,
            },
        ],
        deleteModalGroupId: [
            null as string | null,
            {
                setDeleteModalGroupId: (_, { id }) => id,
                deleteTriggerGroup: () => null, // Close modal after deleting
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
        hasLegacyTriggers: [
            (s) => [s.currentTeam],
            (team): boolean => {
                if (!team) {
                    return false
                }
                const hasUrlTriggers = (team.session_recording_url_trigger_config?.length ?? 0) > 0
                const hasEventTriggers = (team.session_recording_event_trigger_config?.length ?? 0) > 0
                const hasFeatureFlag = !!team.session_recording_linked_flag
                const hasSampling = !!(
                    team.session_recording_sample_rate && parseFloat(team.session_recording_sample_rate) < 1
                )
                return hasUrlTriggers || hasEventTriggers || hasFeatureFlag || hasSampling
            },
        ],
        shouldShowMigrationBanner: [
            (s) => [s.triggerGroups, s.hasLegacyTriggers],
            (triggerGroups, hasLegacyTriggers): boolean => {
                // Show banner if there are legacy triggers configured but no V2 groups
                return hasLegacyTriggers && triggerGroups.length === 0
            },
        ],
        previewLegacyGroups: [
            (s) => [s.currentTeam],
            (team): SessionRecordingTriggerGroup[] => {
                if (!team) {
                    return []
                }

                const sampleRate = team.session_recording_sample_rate
                    ? parseFloat(team.session_recording_sample_rate)
                    : 1
                const minDurationMs = team.session_recording_minimum_duration_milliseconds ?? undefined
                const matchType = team.session_recording_trigger_match_type_config || 'all'

                const events: EventTriggerConfig[] | undefined =
                    team.session_recording_event_trigger_config &&
                    team.session_recording_event_trigger_config.length > 0
                        ? team.session_recording_event_trigger_config
                              .filter((e): e is string => typeof e === 'string' && e.length > 0)
                              .map((name) => ({ name }))
                        : undefined

                const urls =
                    team.session_recording_url_trigger_config && team.session_recording_url_trigger_config.length > 0
                        ? team.session_recording_url_trigger_config
                        : undefined

                const flag = team.session_recording_linked_flag
                    ? typeof team.session_recording_linked_flag === 'string'
                        ? team.session_recording_linked_flag
                        : team.session_recording_linked_flag.key
                    : undefined

                const hasAnyTriggers = urls || events || flag
                const hasSampling = sampleRate < 1

                // If "ANY" match type with triggers AND sampling, create 2 groups:
                // 1. Combined triggers group with 100% sampling
                // 2. Baseline sampling group (no conditions)
                if (matchType === 'any' && hasAnyTriggers && hasSampling) {
                    return [
                        // Group 1: All triggers combined with ANY match type
                        {
                            id: uuid(),
                            name: 'Migrated trigger conditions',
                            sampleRate: 1,
                            minDurationMs,
                            conditions: {
                                matchType: 'any',
                                urls,
                                events,
                                flag,
                            },
                        },
                        // Group 2: Baseline sampling (no conditions)
                        {
                            id: uuid(),
                            name: 'Migrated baseline sampling',
                            sampleRate,
                            minDurationMs,
                            conditions: {
                                matchType: 'all',
                            },
                        },
                    ]
                }

                // Otherwise, create a single group
                return [
                    {
                        id: uuid(),
                        name: 'Migrated trigger conditions',
                        sampleRate,
                        minDurationMs,
                        conditions: {
                            matchType,
                            events,
                            urls,
                            flag,
                        },
                    },
                ]
            },
        ],
        legacyTriggersPreview: [
            (s) => [s.currentTeam],
            (
                team
            ): {
                sampleRate: number
                minDurationMs: number | undefined
                matchType: 'any' | 'all'
                urls: UrlTriggerConfig[]
                events: string[]
                flag: string | LinkedFeatureFlag | null
                hasConditions: boolean
            } => {
                const sampleRate = team?.session_recording_sample_rate
                    ? parseFloat(team.session_recording_sample_rate)
                    : 1
                const minDurationMs = team?.session_recording_minimum_duration_milliseconds ?? undefined
                const matchType = team?.session_recording_trigger_match_type_config || 'all'
                const urls = team?.session_recording_url_trigger_config || []
                const events: string[] = (team?.session_recording_event_trigger_config || []).filter(
                    (e): e is string => typeof e === 'string' && e.length > 0
                )
                const flag = team?.session_recording_linked_flag || null
                const hasConditions = urls.length > 0 || events.length > 0 || !!flag

                return { sampleRate, minDurationMs, matchType, urls, events, flag, hasConditions }
            },
        ],
    }),
    listeners(({ asyncActions }) => ({
        addTriggerGroup: async () => {
            // Auto-save after adding
            await asyncActions.saveConfig()
        },
        addMultipleTriggerGroups: async () => {
            // Auto-save after adding multiple
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
    })),
    // Load config from currentTeam on mount
    afterMount(({ actions, values }) => {
        if (values.currentTeam?.session_recording_trigger_groups) {
            actions.setTriggerGroupsConfig(values.currentTeam.session_recording_trigger_groups)
        }
    }),
])
