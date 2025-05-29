import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    CurrencyCode,
    MarketingAnalyticsConfig,
    MarketingAnalyticsSchema,
    SourceMap,
} from '~/queries/schema/schema-general'
import { Region } from '~/types'

import type { marketingAnalyticsSettingsLogicType } from './marketingAnalyticsSettingsLogicType'

const createEmptyConfig = (region: Region | null | undefined): MarketingAnalyticsConfig => ({
    sources_map: {},
    base_currency: region === Region.EU ? CurrencyCode.EUR : CurrencyCode.USD,
})

export const marketingAnalyticsSettingsLogic = kea<marketingAnalyticsSettingsLogicType>([
    path(['scenes', 'web-analytics', 'marketingAnalyticsSettingsLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeam', 'currentTeamId'],
            preflightLogic,
            ['preflight'],
            dataWarehouseSettingsLogic,
            ['dataWarehouseSources'],
        ],
        actions: [teamLogic, ['updateCurrentTeam'], dataWarehouseSettingsLogic, ['updateSource']],
    })),
    actions({
        updateBaseCurrency: (baseCurrency: CurrencyCode) => ({ baseCurrency }),
        updateSourceMapping: (tableId: string, fieldName: MarketingAnalyticsSchema, columnName: string | null) => ({
            tableId,
            fieldName,
            columnName,
        }),
        save: true,
        resetConfig: true,
    }),
    reducers(({ values }) => ({
        marketingAnalyticsConfig: [
            null as MarketingAnalyticsConfig | null,
            {
                updateBaseCurrency: (state: MarketingAnalyticsConfig | null, { baseCurrency }) => {
                    if (!state) {
                        return state
                    }

                    return { ...state, base_currency: baseCurrency }
                },
                updateSourceMapping: (state: MarketingAnalyticsConfig | null, { tableId, fieldName, columnName }) => {
                    if (!state) {
                        return state
                    }

                    const updatedSourcesMap = { ...state.sources_map }
                    if (!updatedSourcesMap[tableId]) {
                        updatedSourcesMap[tableId] = {} as SourceMap
                    }

                    if (columnName === undefined) {
                        // Remove the field if columnName is undefined
                        delete updatedSourcesMap[tableId][fieldName]
                        // If source becomes empty, remove it entirely
                        if (Object.keys(updatedSourcesMap[tableId]).length === 0) {
                            delete updatedSourcesMap[tableId]
                        }
                    } else {
                        updatedSourcesMap[tableId] = {
                            ...updatedSourcesMap[tableId],
                            [fieldName]: columnName || undefined,
                        }
                    }
                    return { ...state, sources_map: updatedSourcesMap }
                },
                resetConfig: () => {
                    return values.savedMarketingAnalyticsConfig
                },
            },
        ],
        savedMarketingAnalyticsConfig: [
            // TODO: Check how to pass the preflight region here
            values.currentTeam?.marketing_analytics_config || createEmptyConfig(null),
            {
                updateCurrentTeam: (_, { marketing_analytics_config }) => {
                    // TODO: Check how to pass the preflight region here
                    return marketing_analytics_config || createEmptyConfig(null)
                },
            },
        ],
    })),
    selectors({
        baseCurrency: [
            (s) => [s.marketingAnalyticsConfig],
            (marketingAnalyticsConfig: MarketingAnalyticsConfig | null) =>
                marketingAnalyticsConfig?.base_currency || CurrencyCode.USD,
        ],

        sources_map: [
            (s) => [s.marketingAnalyticsConfig],
            (marketingAnalyticsConfig: MarketingAnalyticsConfig | null) => marketingAnalyticsConfig?.sources_map || {},
        ],

        changesMadeToSources: [
            (s) => [s.marketingAnalyticsConfig, s.savedMarketingAnalyticsConfig],
            (config: MarketingAnalyticsConfig | null, savedConfig: MarketingAnalyticsConfig | null): boolean => {
                return !!config && !!savedConfig && !objectsEqual(config.sources_map, savedConfig.sources_map)
            },
        ],
        saveSourcesDisabledReason: [
            (s) => [s.marketingAnalyticsConfig, s.changesMadeToSources],
            (config: MarketingAnalyticsConfig | null, changesMade: boolean): string | null => {
                if (!config) {
                    return 'Loading...'
                }
                if (!changesMade) {
                    return 'No changes to save'
                }
                return null
            },
        ],
    }),
    listeners(({ actions, values }) => {
        const updateCurrentTeam = (): void => {
            if (values.marketingAnalyticsConfig) {
                const payload = { marketing_analytics_config: values.marketingAnalyticsConfig }
                actions.updateCurrentTeam(payload)
            }
        }

        return {
            updateBaseCurrency: updateCurrentTeam,
            updateSourceMapping: updateCurrentTeam,
            save: updateCurrentTeam,
        }
    }),
    loaders(({ values }) => ({
        marketingAnalyticsConfig: {
            loadMarketingAnalyticsConfig: async () => {
                if (values.currentTeam) {
                    return values.currentTeam.marketing_analytics_config || createEmptyConfig(values.preflight?.region)
                }
                return null
            },
        },
    })),
    beforeUnload(({ actions, values }) => ({
        enabled: () => values.changesMadeToSources,
        message: 'Changes you made will be discarded. Make sure you save your changes before leaving this page.',
        onConfirm: () => {
            actions.resetConfig()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadMarketingAnalyticsConfig()
    }),
])
