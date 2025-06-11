import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { teamLogic } from 'scenes/teamLogic'
import { MarketingAnalyticsSchema } from 'scenes/web-analytics/tabs/marketing-analytics/utils'

import { MarketingAnalyticsConfig, SourceMap } from '~/queries/schema/schema-general'

import type { marketingAnalyticsSettingsLogicType } from './marketingAnalyticsSettingsLogicType'

const createEmptyConfig = (): MarketingAnalyticsConfig => ({
    sources_map: {},
})

export const marketingAnalyticsSettingsLogic = kea<marketingAnalyticsSettingsLogicType>([
    path(['scenes', 'web-analytics', 'marketingAnalyticsSettingsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam', 'currentTeamId']],
        actions: [teamLogic, ['updateCurrentTeam']],
    })),
    actions({
        updateSourceMapping: (tableId: string, fieldName: MarketingAnalyticsSchema, columnName: string | null) => ({
            tableId,
            fieldName,
            columnName,
        }),
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

                    if (columnName === null) {
                        // Remove the field if columnName is undefined
                        delete updatedSourcesMap[tableId][fieldName]
                        // If source becomes empty, remove it entirely
                        if (Object.keys(updatedSourcesMap[tableId]).length === 0) {
                            delete updatedSourcesMap[tableId]
                        }
                    } else {
                        updatedSourcesMap[tableId] = {
                            ...updatedSourcesMap[tableId],
                            [fieldName]: columnName ?? undefined,
                        }
                    }
                    return { ...state, sources_map: updatedSourcesMap }
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
    afterMount(({ actions }) => {
        actions.loadMarketingAnalyticsConfig()
    }),
])
