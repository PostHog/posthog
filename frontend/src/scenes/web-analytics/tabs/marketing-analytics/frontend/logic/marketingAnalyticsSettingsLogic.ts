import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { MarketingAnalyticsSchema, SourceMap } from 'scenes/web-analytics/tabs/marketing-analytics/utils'

import { MarketingAnalyticsConfig } from '~/queries/schema/schema-general'

import type { marketingAnalyticsSettingsLogicType } from './marketingAnalyticsSettingsLogicType'

const createEmptyConfig = (): MarketingAnalyticsConfig => ({
    sources_map: {},
})

export const marketingAnalyticsSettingsLogic = kea<marketingAnalyticsSettingsLogicType>([
    path(['scenes', 'web-analytics', 'marketingAnalyticsSettingsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam', 'currentTeamId'], dataWarehouseSettingsLogic, ['dataWarehouseSources']],
        actions: [teamLogic, ['updateCurrentTeam']],
    })),
    actions({
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
            values.currentTeam?.marketing_analytics_config || createEmptyConfig(),
            {
                updateCurrentTeam: (_, { marketing_analytics_config }) => {
                    return marketing_analytics_config || createEmptyConfig()
                },
            },
        ],
    })),
    selectors({
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
            updateSourceMapping: updateCurrentTeam,
            save: updateCurrentTeam,
        }
    }),
    loaders(({ values }) => ({
        marketingAnalyticsConfig: {
            loadMarketingAnalyticsConfig: async () => {
                if (values.currentTeam) {
                    return values.currentTeam.marketing_analytics_config || createEmptyConfig()
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
