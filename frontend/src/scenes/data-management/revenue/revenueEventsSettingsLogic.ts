import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'
import { TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import {
    CurrencyCode,
    DataTableNode,
    NodeKind,
    RevenueExampleEventsQuery,
    RevenueTrackingConfig,
    RevenueTrackingEventItem,
} from '~/queries/schema/schema-general'

import type { revenueEventsSettingsLogicType } from './revenueEventsSettingsLogicType'

const createEmptyConfig = (): RevenueTrackingConfig => ({ events: [], baseCurrency: undefined })

export const revenueEventsSettingsLogic = kea<revenueEventsSettingsLogicType>([
    path(['scenes', 'data-management', 'revenue', 'revenueEventsSettingsLogic']),
    connect({
        values: [teamLogic, ['currentTeam', 'currentTeamId']],
        actions: [teamLogic, ['updateCurrentTeam']],
    }),
    actions({
        addEvent: (eventName: TaxonomicFilterValue) => ({ eventName }),
        deleteEvent: (eventName: string) => ({ eventName }),
        resetEvents: true,
        updatePropertyName: (eventName: string, revenueProperty: string) => ({ eventName, revenueProperty }),
        updateCurrencyPropertyName: (eventName: string, revenueCurrencyProperty: string) => ({
            eventName,
            revenueCurrencyProperty,
        }),
        updateBaseCurrency: (baseCurrency: CurrencyCode) => ({ baseCurrency }),
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
                updateBaseCurrency: (state, { baseCurrency }) => {
                    if (!state) {
                        return state
                    }

                    return { ...state, baseCurrency }
                },
                resetEvents: () => {
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
            actions.resetEvents()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRevenueTrackingConfig()
    }),
])
