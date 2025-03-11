import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import {
    CurrencyCode,
    DataTableNode,
    NodeKind,
    RevenueExampleEventsQuery,
    RevenueExampleExternalTablesQuery,
    RevenueTrackingConfig,
    RevenueTrackingEventItem,
} from '~/queries/schema/schema-general'

import type { revenueEventsSettingsLogicType } from './revenueEventsSettingsLogicType'

const createEmptyConfig = (): RevenueTrackingConfig => ({
    events: [],
    externalDataSchemas: [],
    baseCurrency: undefined,
})

export const revenueEventsSettingsLogic = kea<revenueEventsSettingsLogicType>([
    path(['scenes', 'data-management', 'revenue', 'revenueEventsSettingsLogic']),
    connect({
        values: [teamLogic, ['currentTeam', 'currentTeamId']],
        actions: [teamLogic, ['updateCurrentTeam']],
    }),
    actions({
        updateBaseCurrency: (baseCurrency: CurrencyCode) => ({ baseCurrency }),

        addEvent: (eventName: string) => ({ eventName }),
        deleteEvent: (eventName: string) => ({ eventName }),
        updateEventRevenueProperty: (eventName: string, revenueProperty: string) => ({ eventName, revenueProperty }),
        updateEventRevenueCurrencyProperty: (eventName: string, revenueCurrencyProperty: string) => ({
            eventName,
            revenueCurrencyProperty,
        }),

        addExternalDataSchema: (externalDataSchemaName: string) => ({ externalDataSchemaName }),
        deleteExternalDataSchema: (externalDataSchemaName: string) => ({ externalDataSchemaName }),
        updateExternalDataSchemaRevenueColumn: (externalDataSchemaName: string, revenueColumn: string) => ({
            externalDataSchemaName,
            revenueColumn,
        }),
        updateExternalDataSchemaRevenueCurrencyColumn: (
            externalDataSchemaName: string,
            revenueCurrencyColumn: string
        ) => ({
            externalDataSchemaName,
            revenueCurrencyColumn,
        }),

        resetConfig: true,
    }),
    reducers(({ values }) => ({
        revenueTrackingConfig: [
            null as RevenueTrackingConfig | null,
            {
                updateBaseCurrency: (state, { baseCurrency }) => {
                    if (!state) {
                        return state
                    }

                    return { ...state, baseCurrency }
                },
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

                    return {
                        ...state,
                        events: [
                            ...state.events,
                            {
                                eventName,
                                revenueProperty: 'revenue',
                                revenueCurrencyProperty: undefined,
                            },
                        ],
                    }
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
                updateCurrencyPropertyName: (state, { eventName, revenueCurrencyProperty }) => {
                    if (!state) {
                        return state
                    }

                    return {
                        ...state,
                        events: state.events.map((item) => {
                            if (item.eventName === eventName) {
                                return { ...item, revenueCurrencyProperty }
                            }
                            return item
                        }),
                    }
                },
                addExternalDataSchema: (state, { externalDataSchemaName }) => {
                    if (!state) {
                        return state
                    }

                    return {
                        ...state,
                        externalDataSchemas: [
                            ...state.externalDataSchemas,
                            {
                                name: externalDataSchemaName,
                                revenueColumn: 'revenue',
                                revenueCurrencyColumn: undefined,
                            },
                        ],
                    }
                },
                deleteExternalDataSchema: (state, { externalDataSchemaName }) => {
                    if (!state) {
                        return state
                    }
                    return {
                        ...state,
                        externalDataSchemas: state.externalDataSchemas.filter(
                            (item) => item.name !== externalDataSchemaName
                        ),
                    }
                },
                updateExternalDataSchemaRevenueColumn: (state, { externalDataSchemaName, revenueColumn }) => {
                    if (!state) {
                        return state
                    }
                    return {
                        ...state,
                        externalDataSchemas: state.externalDataSchemas.map((item) => {
                            if (item.name === externalDataSchemaName) {
                                return { ...item, revenueColumn }
                            }
                            return item
                        }),
                    }
                },
                updateExternalDataSchemaRevenueCurrencyColumn: (
                    state,
                    { externalDataSchemaName, revenueCurrencyColumn }
                ) => {
                    if (!state) {
                        return state
                    }
                    return {
                        ...state,
                        externalDataSchemas: state.externalDataSchemas.map((item) => {
                            if (item.name === externalDataSchemaName) {
                                return { ...item, revenueCurrencyColumn }
                            }
                            return item
                        }),
                    }
                },
                resetConfig: () => {
                    return values.savedRevenueTrackingConfig
                },
            },
        ],
        savedRevenueTrackingConfig: [
            values.currentTeam?.revenue_tracking_config || createEmptyConfig(),
            {
                saveChanges: (_, team) => team.revenue_tracking_config || createEmptyConfig(),
            },
        ],
    })),
    selectors({
        events: [
            (s) => [s.revenueTrackingConfig],
            (revenueTrackingConfig: RevenueTrackingConfig | null) => revenueTrackingConfig?.events || [],
        ],
        externalDataSchemas: [
            (s) => [s.revenueTrackingConfig],
            (revenueTrackingConfig: RevenueTrackingConfig | null) => revenueTrackingConfig?.externalDataSchemas || [],
        ],
        baseCurrency: [
            (s) => [s.revenueTrackingConfig],
            (revenueTrackingConfig: RevenueTrackingConfig | null) =>
                revenueTrackingConfig?.baseCurrency || CurrencyCode.USD,
        ],
        saveDisabledReason: [
            (s) => [s.revenueTrackingConfig, s.changesMade],
            (config, changesMade): string | null => {
                if (!config) {
                    return 'Loading...'
                }
                if (!changesMade) {
                    return 'No changes to save'
                }
                return null
            },
        ],
        changesMade: [
            (s) => [s.revenueTrackingConfig, s.savedRevenueTrackingConfig],
            (config, savedConfig): boolean => {
                return !!config && !objectsEqual(config, savedConfig)
            },
        ],

        exampleEventsQuery: [
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
                    showPropertyFilter: false,
                    source,
                }

                return query
            },
        ],

        exampleExternalDataSchemasQuery: [
            (s) => [s.revenueTrackingConfig],
            (revenueTrackingConfig: RevenueTrackingConfig | null) => {
                if (!revenueTrackingConfig) {
                    return null
                }

                const source: RevenueExampleExternalTablesQuery = {
                    kind: NodeKind.RevenueExampleExternalTablesQuery,
                    revenueTrackingConfig: revenueTrackingConfig,
                }

                const query: DataTableNode = {
                    kind: NodeKind.DataTableNode,
                    full: true,
                    showPropertyFilter: false,
                    source,
                }

                return query
            },
        ],
    }),
    loaders(({ values, actions }) => ({
        saveChanges: {
            save: () => {
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
    beforeUnload(({ actions, values }) => ({
        enabled: () => values.changesMade,
        message: 'Changes you made will be discarded. Make sure you save your changes before leaving this page.',
        onConfirm: () => {
            actions.resetConfig()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRevenueTrackingConfig()
    }),
])
