import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import {
    DataTableNode,
    NodeKind,
    RevenueExampleEventsQuery,
    RevenueTrackingConfig,
    RevenueTrackingEventItem,
} from '~/queries/schema/schema-general'

import type { revenueEventsSettingsLogicType } from './revenueEventsSettingsLogicType'

const createEmptyConfig = (): RevenueTrackingConfig => ({ events: [] })

export const revenueEventsSettingsLogic = kea<revenueEventsSettingsLogicType>([
    path(['scenes', 'data-management', 'revenue', 'revenueEventsSettingsLogic']),
    connect({
        values: [teamLogic, ['currentTeam', 'currentTeamId']],
        actions: [teamLogic, ['updateCurrentTeam']],
    }),
    actions({
        addEvent: (eventName: TaxonomicFilterValue) => ({ eventName }),
        deleteEvent: (eventName: string) => ({ eventName }),
        updatePropertyName: (eventName: string, revenueProperty: string) => ({ eventName, revenueProperty }),
    }),
    reducers(({ values }) => ({
        revenueTrackingConfig: [
            null as RevenueTrackingConfig | null,
            {
                addEvent: (state, { eventName }) => {
                    if (
                        !state ||
                        !eventName ||
                        typeof eventName !== 'string' ||
                        eventName == '$pageview' ||
                        eventName == '$autocapture'
                    ) {
                        return state
                    }
                    const existingEvents = new Set(state.events.map((item: RevenueTrackingEventItem) => item.eventName))
                    if (existingEvents.has(eventName)) {
                        return state
                    }

                    return { ...state, events: [...state.events, { eventName, revenueProperty: 'revenue' }] }
                },
                deleteEvent: (state, { eventName }) => {
                    if (!state) {
                        return state
                    }
                    return { ...state, events: state.events.filter((item) => item.eventName !== eventName) }
                },
                updatePropertyName: (state, { eventName, revenueProperty }) => {
                    if (!state) {
                        return state
                    }
                    return {
                        ...state,
                        events: state.events.map((item) => {
                            if (item.eventName === eventName) {
                                return { ...item, revenueProperty }
                            }
                            return item
                        }),
                    }
                },
            },
        ],
        savedRevenueTrackingConfig: [
            values.currentTeam?.revenue_tracking_config || {},
            {
                saveChanges: (_, team) => team.revenue_tracking_config || {},
            },
        ],
    })),
    selectors({
        events: [
            (s) => [s.revenueTrackingConfig],
            (revenueTrackingConfig: RevenueTrackingConfig | null) => revenueTrackingConfig?.events || [],
        ],
        saveDisabledReason: [
            (s) => [s.revenueTrackingConfig, s.savedRevenueTrackingConfig],
            (config, savedConfig): string | null => {
                if (!config) {
                    return 'Loading...'
                }
                if (objectsEqual(config, savedConfig)) {
                    return 'No changes to save'
                }
                return null
            },
        ],
        eventsQuery: [
            (s) => [s.revenueTrackingConfig],
            (revenueTrackingConfig: RevenueTrackingConfig | null) => {
                if (!revenueTrackingConfig) {
                    return null
                }

                const source: RevenueExampleEventsQuery = {
                    kind: NodeKind.RevenueExampleEventsQuery,
                    revenueTrackingConfig: revenueTrackingConfig,
                }

                const query: DataTableNode = {
                    kind: NodeKind.DataTableNode,
                    full: true,
                    source,
                }
                return query
            },
        ],
    }),
    loaders(({ values, actions }) => ({
        saveChanges: {
            save: () => {
                if (values.saveDisabledReason) {
                    return null
                }
                actions.updateCurrentTeam({
                    revenue_tracking_config: values.revenueTrackingConfig || createEmptyConfig(),
                })
                return null
            },
        },
        revenueTrackingConfig: {
            loadRevenueTrackingConfig: async () => {
                if (values.currentTeam) {
                    return values.currentTeam.revenue_tracking_config || createEmptyConfig()
                }
                return null
            },
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRevenueTrackingConfig()
    }),
])
