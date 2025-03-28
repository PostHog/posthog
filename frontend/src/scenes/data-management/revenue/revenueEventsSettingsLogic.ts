import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    CurrencyCode,
    DataTableNode,
    NodeKind,
    RevenueCurrencyPropertyConfig,
    RevenueExampleDataWarehouseTablesQuery,
    RevenueExampleEventsQuery,
    RevenueTrackingConfig,
    RevenueTrackingDataWarehouseTable,
    RevenueTrackingEventItem,
} from '~/queries/schema/schema-general'
import { Region } from '~/types'

import type { revenueEventsSettingsLogicType } from './revenueEventsSettingsLogicType'

const createEmptyConfig = (region: Region | null | undefined): RevenueTrackingConfig => ({
    events: [],
    dataWarehouseTables: [],

    // Region won't be always set because we might mount this before we mount preflightLogic
    // so we default to USD if we can't determine the region
    baseCurrency: region === Region.EU ? CurrencyCode.EUR : CurrencyCode.USD,
})

export const revenueEventsSettingsLogic = kea<revenueEventsSettingsLogicType>([
    path(['scenes', 'data-management', 'revenue', 'revenueEventsSettingsLogic']),
    connect({
        values: [teamLogic, ['currentTeam', 'currentTeamId'], preflightLogic, ['preflight']],
        actions: [teamLogic, ['updateCurrentTeam']],
    }),
    actions({
        updateBaseCurrency: (baseCurrency: CurrencyCode) => ({ baseCurrency }),

        addEvent: (eventName: string) => ({ eventName }),
        deleteEvent: (eventName: string) => ({ eventName }),
        updateEventRevenueProperty: (eventName: string, revenueProperty: string) => ({ eventName, revenueProperty }),
        updateEventRevenueCurrencyProperty: (
            eventName: string,
            revenueCurrencyProperty: RevenueCurrencyPropertyConfig
        ) => ({
            eventName,
            revenueCurrencyProperty,
        }),

        addDataWarehouseTable: (dataWarehouseTable: RevenueTrackingDataWarehouseTable) => dataWarehouseTable,
        deleteDataWarehouseTable: (dataWarehouseTableName: string) => ({ dataWarehouseTableName }),
        updateDataWarehouseTableColumn: (
            dataWarehouseTableName: string,
            key: keyof RevenueTrackingDataWarehouseTable & ('timestampColumn' | 'revenueColumn' | 'distinctIdColumn'),
            newValue: string
        ) => ({ dataWarehouseTableName, key, newValue }),
        updateDataWarehouseTableRevenueCurrencyColumn: (
            dataWarehouseTableName: string,
            revenueCurrencyColumn: RevenueCurrencyPropertyConfig
        ) => ({ dataWarehouseTableName, revenueCurrencyColumn }),

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
                                revenueCurrencyProperty: { static: state.baseCurrency },
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
                updateEventRevenueProperty: (state, { eventName, revenueProperty }) => {
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
                updateEventRevenueCurrencyProperty: (state, { eventName, revenueCurrencyProperty }) => {
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
                addDataWarehouseTable: (state, newDataWarehouseTable) => {
                    if (!state) {
                        return state
                    }

                    // Guarantee we've only got a single external data schema per table
                    if (state.dataWarehouseTables.some((item) => item.tableName === newDataWarehouseTable.tableName)) {
                        return state
                    }

                    return {
                        ...state,
                        dataWarehouseTables: [...state.dataWarehouseTables, newDataWarehouseTable],
                    }
                },
                deleteDataWarehouseTable: (state, { dataWarehouseTableName }) => {
                    if (!state) {
                        return state
                    }
                    return {
                        ...state,
                        dataWarehouseTables: state.dataWarehouseTables.filter(
                            (item) => item.tableName !== dataWarehouseTableName
                        ),
                    }
                },
                updateDataWarehouseTableColumn: (state, { dataWarehouseTableName, key, newValue }) => {
                    if (!state) {
                        return state
                    }

                    return {
                        ...state,
                        dataWarehouseTables: state.dataWarehouseTables.map((item) => {
                            if (item.tableName === dataWarehouseTableName) {
                                return { ...item, [key]: newValue }
                            }

                            return item
                        }),
                    }
                },
                updateDataWarehouseTableRevenueCurrencyColumn: (
                    state,
                    { dataWarehouseTableName, revenueCurrencyColumn }
                ) => {
                    if (!state) {
                        return state
                    }

                    return {
                        ...state,
                        dataWarehouseTables: state.dataWarehouseTables.map((item) => {
                            if (item.tableName === dataWarehouseTableName) {
                                return { ...item, revenueCurrencyColumn }
                            }

                            return item
                        }),
                    }
                },
                resetConfig: () => {
                    return values.savedRevenueTrackingConfig
                },
                updateCurrentTeam: (_, { revenue_tracking_config }) => {
                    // TODO: Check how to pass the preflight region here
                    return revenue_tracking_config || createEmptyConfig(null)
                },
            },
        ],
        savedRevenueTrackingConfig: [
            // TODO: Check how to pass the preflight region here
            values.currentTeam?.revenue_tracking_config || createEmptyConfig(null),
            {
                updateCurrentTeam: (_, { revenue_tracking_config }) => {
                    // TODO: Check how to pass the preflight region here
                    return revenue_tracking_config || createEmptyConfig(null)
                },
            },
        ],
    })),
    selectors({
        events: [
            (s) => [s.revenueTrackingConfig],
            (revenueTrackingConfig: RevenueTrackingConfig | null) => revenueTrackingConfig?.events || [],
        ],
        dataWarehouseTables: [
            (s) => [s.revenueTrackingConfig],
            (revenueTrackingConfig: RevenueTrackingConfig | null) => revenueTrackingConfig?.dataWarehouseTables || [],
        ],
        baseCurrency: [
            (s) => [s.revenueTrackingConfig],
            (revenueTrackingConfig: RevenueTrackingConfig | null) =>
                revenueTrackingConfig?.baseCurrency || CurrencyCode.USD,
        ],

        changesMadeToEvents: [
            (s) => [s.revenueTrackingConfig, s.savedRevenueTrackingConfig],
            (config, savedConfig): boolean => {
                return !!config && !objectsEqual(config.events, savedConfig.events)
            },
        ],

        changesMadeToDataWarehouseTables: [
            (s) => [s.revenueTrackingConfig, s.savedRevenueTrackingConfig],
            (config, savedConfig): boolean => {
                return !!config && !objectsEqual(config.dataWarehouseTables, savedConfig.dataWarehouseTables)
            },
        ],

        saveEventsDisabledReason: [
            (s) => [s.revenueTrackingConfig, s.changesMadeToEvents],
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
        saveDataWarehouseTablesDisabledReason: [
            (s) => [s.revenueTrackingConfig, s.changesMadeToDataWarehouseTables],
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

        exampleEventsQuery: [
            (s) => [s.savedRevenueTrackingConfig],
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
        exampleDataWarehouseTablesQuery: [
            (s) => [s.savedRevenueTrackingConfig],
            (revenueTrackingConfig: RevenueTrackingConfig | null) => {
                if (!revenueTrackingConfig) {
                    return null
                }

                const source: RevenueExampleDataWarehouseTablesQuery = {
                    kind: NodeKind.RevenueExampleDataWarehouseTablesQuery,
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
                    revenue_tracking_config:
                        values.revenueTrackingConfig || createEmptyConfig(values.preflight?.region),
                })
                return null
            },
        },
        revenueTrackingConfig: {
            loadRevenueTrackingConfig: async () => {
                if (values.currentTeam) {
                    return values.currentTeam.revenue_tracking_config || createEmptyConfig(values.preflight?.region)
                }
                return null
            },
        },
    })),
    beforeUnload(({ actions, values }) => ({
        enabled: () => values.changesMadeToEvents || values.changesMadeToDataWarehouseTables,
        message: 'Changes you made will be discarded. Make sure you save your changes before leaving this page.',
        onConfirm: () => {
            actions.resetConfig()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRevenueTrackingConfig()
    }),
])
