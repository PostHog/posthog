import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    AttributionMode,
    CampaignFieldPreference,
    ConversionGoalFilter,
    DatabaseSchemaDataWarehouseTable,
    HogQLQueryResponse,
    MARKETING_CAMPAIGN_TABLE_PATTERNS,
    MARKETING_INTEGRATION_FIELD_MAP,
    MarketingAnalyticsColumnsSchemaNames,
    MarketingAnalyticsConfig,
    NativeMarketingSource,
    NodeKind,
    ProductIntentContext,
    ProductKey,
    SourceMap,
} from '~/queries/schema/schema-general'
import { ExternalDataSource } from '~/types'

import { IntegrationSettingsTab } from '../components/settings/IntegrationSettingsModal'
import type { marketingAnalyticsSettingsLogicType } from './marketingAnalyticsSettingsLogicType'
import { DEFAULT_ATTRIBUTION_WINDOW_DAYS, generateUniqueName } from './utils'

export interface IntegrationSettingsModalState {
    isOpen: boolean
    integration: NativeMarketingSource | null
    initialTab: IntegrationSettingsTab
    initialUtmValue: string
}

const createEmptyConfig = (): MarketingAnalyticsConfig => ({
    sources_map: {},
    conversion_goals: [],
    attribution_window_days: DEFAULT_ATTRIBUTION_WINDOW_DAYS,
    attribution_mode: AttributionMode.LastTouch,
    campaign_name_mappings: {},
    custom_source_mappings: {},
    campaign_field_preferences: {},
})

export const marketingAnalyticsSettingsLogic = kea<marketingAnalyticsSettingsLogicType>([
    path(['scenes', 'web-analytics', 'marketingAnalyticsSettingsLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeam', 'currentTeamId'],
            dataWarehouseSettingsLogic,
            ['dataWarehouseTables', 'dataWarehouseSources'],
        ],
        actions: [teamLogic, ['updateCurrentTeam', 'addProductIntent']],
    })),
    actions({
        updateSourceMapping: (
            tableId: string,
            fieldName: MarketingAnalyticsColumnsSchemaNames,
            columnName: string | null
        ) => ({
            tableId,
            fieldName,
            columnName,
        }),
        updateConversionGoals: (conversionGoals: ConversionGoalFilter[]) => ({
            conversionGoals,
        }),
        addOrUpdateConversionGoal: (conversionGoal: ConversionGoalFilter) => ({
            conversionGoal,
        }),
        removeConversionGoal: (goalId: string) => ({
            goalId,
        }),
        updateAttributionWindowDays: (days: number) => ({
            days,
        }),
        updateAttributionMode: (mode: AttributionMode) => ({
            mode,
        }),
        updateCampaignNameMappings: (campaignNameMappings: Record<string, Record<string, string[]>>) => ({
            campaignNameMappings,
        }),
        updateCustomSourceMappings: (customSourceMappings: Record<string, string[]>) => ({
            customSourceMappings,
        }),
        updateCampaignFieldPreferences: (campaignFieldPreferences: Record<string, CampaignFieldPreference>) => ({
            campaignFieldPreferences,
        }),
        loadIntegrationCampaigns: (integration: string) => ({ integration }),
        setIntegrationCampaigns: (integration: string, campaigns: Array<{ name: string; id: string }>) => ({
            integration,
            campaigns,
        }),
        openIntegrationSettingsModal: (
            integration: NativeMarketingSource,
            initialTab: IntegrationSettingsTab,
            initialUtmValue: string
        ) => ({ integration, initialTab, initialUtmValue }),
        closeIntegrationSettingsModal: true,
    }),
    reducers(({ values }) => ({
        marketingAnalyticsConfig: [
            null as MarketingAnalyticsConfig | null,
            {
                updateConversionGoals: (state: MarketingAnalyticsConfig | null, { conversionGoals }) => {
                    if (!state) {
                        return { ...createEmptyConfig(), conversion_goals: conversionGoals }
                    }
                    return { ...state, conversion_goals: conversionGoals }
                },
                addOrUpdateConversionGoal: (state: MarketingAnalyticsConfig | null, { conversionGoal }) => {
                    if (!state) {
                        return { ...createEmptyConfig(), conversion_goals: [conversionGoal] }
                    }

                    const existingGoals = state.conversion_goals || []
                    const existingIndex = existingGoals.findIndex(
                        (goal) => goal.conversion_goal_id === conversionGoal.conversion_goal_id
                    )

                    let updatedConversionGoal = { ...conversionGoal }

                    // Check for name conflicts with other goals (excluding the current goal if updating)
                    const otherGoals =
                        existingIndex >= 0 ? existingGoals.filter((_, index) => index !== existingIndex) : existingGoals

                    const existingNames = otherGoals.map((goal) => goal.conversion_goal_name)
                    const uniqueName = generateUniqueName(conversionGoal.conversion_goal_name, existingNames)

                    updatedConversionGoal.conversion_goal_name = uniqueName

                    let updatedGoals: ConversionGoalFilter[]
                    if (existingIndex >= 0) {
                        // Update existing goal
                        updatedGoals = [...existingGoals]
                        updatedGoals[existingIndex] = updatedConversionGoal
                    } else {
                        // Add new goal
                        updatedGoals = [...existingGoals, updatedConversionGoal]
                    }

                    return { ...state, conversion_goals: updatedGoals }
                },
                removeConversionGoal: (state: MarketingAnalyticsConfig | null, { goalId }) => {
                    if (!state) {
                        return state
                    }

                    const existingGoals = state.conversion_goals || []
                    const updatedGoals = existingGoals.filter((goal) => goal.conversion_goal_id !== goalId)

                    return { ...state, conversion_goals: updatedGoals }
                },
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
                updateAttributionWindowDays: (state: MarketingAnalyticsConfig | null, { days }) => {
                    if (!state) {
                        return { ...createEmptyConfig(), attribution_window_days: days }
                    }
                    return { ...state, attribution_window_days: days }
                },
                updateAttributionMode: (state: MarketingAnalyticsConfig | null, { mode }) => {
                    if (!state) {
                        return { ...createEmptyConfig(), attribution_mode: mode }
                    }
                    return { ...state, attribution_mode: mode }
                },
                updateCampaignNameMappings: (state: MarketingAnalyticsConfig | null, { campaignNameMappings }) => {
                    if (!state) {
                        return { ...createEmptyConfig(), campaign_name_mappings: campaignNameMappings }
                    }
                    return { ...state, campaign_name_mappings: campaignNameMappings }
                },
                updateCustomSourceMappings: (state: MarketingAnalyticsConfig | null, { customSourceMappings }) => {
                    if (!state) {
                        return { ...createEmptyConfig(), custom_source_mappings: customSourceMappings }
                    }
                    return { ...state, custom_source_mappings: customSourceMappings }
                },
                updateCampaignFieldPreferences: (
                    state: MarketingAnalyticsConfig | null,
                    { campaignFieldPreferences }
                ) => {
                    if (!state) {
                        return { ...createEmptyConfig(), campaign_field_preferences: campaignFieldPreferences }
                    }
                    return { ...state, campaign_field_preferences: campaignFieldPreferences }
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
        integrationCampaigns: [
            {} as Record<string, Array<{ name: string; id: string }>>,
            {
                setIntegrationCampaigns: (state, { integration, campaigns }) => ({
                    ...state,
                    [integration]: campaigns,
                }),
            },
        ],
        integrationCampaignsLoading: [
            {} as Record<string, boolean>,
            {
                loadIntegrationCampaigns: (state, { integration }) => ({
                    ...state,
                    [integration]: true,
                }),
                setIntegrationCampaigns: (state, { integration }) => ({
                    ...state,
                    [integration]: false,
                }),
            },
        ],
        integrationSettingsModal: [
            {
                isOpen: false,
                integration: null,
                initialTab: 'mappings',
                initialUtmValue: '',
            } as IntegrationSettingsModalState,
            {
                openIntegrationSettingsModal: (_, { integration, initialTab, initialUtmValue }) => ({
                    isOpen: true,
                    integration,
                    initialTab,
                    initialUtmValue,
                }),
                closeIntegrationSettingsModal: () => ({
                    isOpen: false,
                    integration: null,
                    initialTab: 'mappings',
                    initialUtmValue: '',
                }),
            },
        ],
    })),
    selectors({
        sources_map: [
            (s) => [s.marketingAnalyticsConfig],
            (marketingAnalyticsConfig: MarketingAnalyticsConfig | null) => marketingAnalyticsConfig?.sources_map || {},
        ],
        conversion_goals: [
            (s) => [s.marketingAnalyticsConfig],
            (marketingAnalyticsConfig: MarketingAnalyticsConfig | null) => {
                return marketingAnalyticsConfig?.conversion_goals || []
            },
        ],
        attribution_window_days: [
            (s) => [s.marketingAnalyticsConfig],
            (marketingAnalyticsConfig: MarketingAnalyticsConfig | null) => {
                return marketingAnalyticsConfig?.attribution_window_days ?? DEFAULT_ATTRIBUTION_WINDOW_DAYS
            },
        ],
        attribution_mode: [
            (s) => [s.marketingAnalyticsConfig],
            (marketingAnalyticsConfig: MarketingAnalyticsConfig | null) => {
                return marketingAnalyticsConfig?.attribution_mode ?? AttributionMode.LastTouch
            },
        ],
        integrationCampaignTables: [
            (s) => [s.dataWarehouseTables, s.dataWarehouseSources],
            (
                dataWarehouseTables: DatabaseSchemaDataWarehouseTable[],
                dataWarehouseSources: { results?: ExternalDataSource[] } | null
            ): Record<string, string> => {
                const result: Record<string, string> = {}
                const sources = dataWarehouseSources?.results || []

                // For each native source, find its campaign table
                for (const source of sources) {
                    const sourceType = source.source_type
                    const patterns = MARKETING_CAMPAIGN_TABLE_PATTERNS[sourceType]
                    if (!patterns) {
                        continue
                    }

                    // Find tables that belong to this source
                    const sourceTables = (dataWarehouseTables || []).filter(
                        (table) => table.source?.source_type === sourceType
                    )

                    // Find the campaign table using the same pattern matching as the backend
                    for (const table of sourceTables) {
                        const tableSuffix = table.name.split('.').pop()?.toLowerCase() || ''

                        const matchesKeyword = patterns.keywords.some((kw: string) => tableSuffix.includes(kw))
                        const matchesExclusion = patterns.exclusions.some((ex: string) => tableSuffix.includes(ex))

                        if (matchesKeyword && !matchesExclusion) {
                            result[sourceType] = table.name
                            break
                        }
                    }
                }

                return result
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

        const trackSourceConfigured = (): void => {
            updateCurrentTeam()
            actions.addProductIntent({
                product_type: ProductKey.MARKETING_ANALYTICS,
                intent_context: ProductIntentContext.MARKETING_ANALYTICS_SOURCE_CONFIGURED,
            })
        }

        const trackSettingsUpdated = (): void => {
            updateCurrentTeam()
            actions.addProductIntent({
                product_type: ProductKey.MARKETING_ANALYTICS,
                intent_context: ProductIntentContext.MARKETING_ANALYTICS_SETTINGS_UPDATED,
            })
        }

        return {
            updateSourceMapping: trackSourceConfigured,
            updateConversionGoals: trackSettingsUpdated,
            addOrUpdateConversionGoal: trackSettingsUpdated,
            removeConversionGoal: trackSettingsUpdated,
            updateAttributionWindowDays: trackSettingsUpdated,
            updateAttributionMode: trackSettingsUpdated,
            updateCampaignNameMappings: trackSettingsUpdated,
            updateCustomSourceMappings: trackSettingsUpdated,
            updateCampaignFieldPreferences: trackSettingsUpdated,
            loadIntegrationCampaigns: async ({ integration }) => {
                const fieldInfo = MARKETING_INTEGRATION_FIELD_MAP[integration]
                if (!fieldInfo) {
                    actions.setIntegrationCampaigns(integration, [])
                    return
                }

                // Get the actual table name from the selector
                const tableName = values.integrationCampaignTables[integration]
                if (!tableName) {
                    // Table not found - integration might not be set up yet
                    actions.setIntegrationCampaigns(integration, [])
                    return
                }

                const query = `SELECT DISTINCT ${fieldInfo.nameField} as name, toString(${fieldInfo.idField}) as id FROM ${tableName} ORDER BY name LIMIT 1000`

                try {
                    const response = await api.query({
                        kind: NodeKind.HogQLQuery,
                        query,
                    })
                    const hogqlResponse = response as HogQLQueryResponse
                    const campaigns = (hogqlResponse.results || []).map((row: any[]) => ({
                        name: String(row[0] || ''),
                        id: String(row[1] || ''),
                    }))
                    actions.setIntegrationCampaigns(integration, campaigns)
                } catch {
                    // Table might not exist or have issues, that's okay
                    actions.setIntegrationCampaigns(integration, [])
                }
            },
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
