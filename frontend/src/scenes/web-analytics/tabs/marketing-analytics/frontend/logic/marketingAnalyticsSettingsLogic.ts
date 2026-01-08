import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    AttributionMode,
    CampaignFieldPreference,
    ConversionGoalFilter,
    CoreEvent,
    DataWarehouseNode,
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
    SchemaMap,
    SourceMap,
} from '~/queries/schema/schema-general'
import { ExternalDataSource } from '~/types'

import { IntegrationSettingsTab } from '../components/settings/IntegrationSettingsModal'
import type { marketingAnalyticsSettingsLogicType } from './marketingAnalyticsSettingsLogicType'
import { DEFAULT_ATTRIBUTION_WINDOW_DAYS, generateUniqueName } from './utils'

/** API response type for core events */
export interface CoreEventResponse {
    id: string
    name: string
    description: string
    category: string
    filter: Record<string, unknown>
    created_at: string
    updated_at: string
}

/** API response type for goal mappings - includes nested core_event */
export interface MarketingAnalyticsGoalMapping {
    id: string
    core_event: CoreEventResponse
    schema_map: Record<string, string | undefined>
    created_at: string
    updated_at: string
}

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
        // Legacy actions for backwards compatibility (deprecated - use goal mappings API)
        updateConversionGoals: (conversionGoals: ConversionGoalFilter[]) => ({
            conversionGoals,
        }),
        addOrUpdateConversionGoal: (conversionGoal: ConversionGoalFilter) => ({
            conversionGoal,
        }),
        removeConversionGoal: (goalId: string) => ({
            goalId,
        }),
        // Core events API actions
        setCoreEvents: (coreEvents: CoreEventResponse[]) => ({ coreEvents }),
        loadCoreEvents: true,
        // Goal mappings API actions
        setGoalMappings: (mappings: MarketingAnalyticsGoalMapping[]) => ({ mappings }),
        loadGoalMappings: true,
        addGoalMapping: (coreEventId: string, schemaMap?: Record<string, string | undefined>) => ({
            coreEventId,
            schemaMap,
        }),
        updateGoalMapping: (mappingId: string, schemaMap: Record<string, string | undefined>) => ({
            mappingId,
            schemaMap,
        }),
        removeGoalMapping: (mappingId: string) => ({ mappingId }),
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
        // Core events from API
        coreEvents: [
            [] as CoreEventResponse[],
            {
                setCoreEvents: (_, { coreEvents }) => coreEvents,
            },
        ],
        // Goal mappings from API
        goalMappings: [
            [] as MarketingAnalyticsGoalMapping[],
            {
                setGoalMappings: (_, { mappings }) => mappings,
            },
        ],
    })),
    selectors({
        sources_map: [
            (s) => [s.marketingAnalyticsConfig],
            (marketingAnalyticsConfig: MarketingAnalyticsConfig | null) => marketingAnalyticsConfig?.sources_map || {},
        ],
        // Legacy selector for backwards compatibility
        conversion_goals: [
            (s) => [s.marketingAnalyticsConfig],
            (marketingAnalyticsConfig: MarketingAnalyticsConfig | null) => {
                return marketingAnalyticsConfig?.conversion_goals || []
            },
        ],
        // Team core events (shared pool) - now loaded from API
        teamCoreEvents: [
            (s) => [s.coreEvents],
            (coreEvents: CoreEventResponse[]): CoreEvent[] => {
                // Convert API response to CoreEvent type used by components
                return coreEvents.map((ce) => ({
                    id: ce.id,
                    name: ce.name,
                    description: ce.description,
                    category: ce.category as CoreEvent['category'],
                    filter: ce.filter as unknown as CoreEvent['filter'],
                }))
            },
        ],
        // Core events that are enabled for marketing analytics (have a mapping)
        enabledCoreEvents: [
            (s) => [s.goalMappings],
            (mappings: MarketingAnalyticsGoalMapping[]): CoreEvent[] => {
                // Goal mappings now include the full core_event object
                return mappings.map((m) => ({
                    id: m.core_event.id,
                    name: m.core_event.name,
                    description: m.core_event.description,
                    category: m.core_event.category as CoreEvent['category'],
                    filter: m.core_event.filter as unknown as CoreEvent['filter'],
                }))
            },
        ],
        // Core events available to add (not yet mapped)
        availableCoreEvents: [
            (s) => [s.teamCoreEvents, s.goalMappings],
            (coreEvents: CoreEvent[], mappings: MarketingAnalyticsGoalMapping[]): CoreEvent[] => {
                const mappedIds = mappings.map((m) => m.core_event.id)
                return coreEvents.filter((event) => !mappedIds.includes(event.id))
            },
        ],
        // Convert enabled core events to ConversionGoalFilter format for queries
        enabledConversionGoalFilters: [
            (s) => [s.goalMappings],
            (mappings: MarketingAnalyticsGoalMapping[]): ConversionGoalFilter[] => {
                return mappings.map((mapping) => {
                    const event = mapping.core_event
                    const filter = event.filter as unknown as CoreEvent['filter']
                    // For DW goals, use UTM fields from mapping and timestamp/distinct_id from goal filter
                    // For events/actions, use defaults (pageview-based attribution)
                    let schemaMap: SchemaMap
                    if (filter.kind === NodeKind.DataWarehouseNode) {
                        const dwFilter = filter as DataWarehouseNode
                        schemaMap = {
                            utm_campaign_name: mapping?.schema_map?.utm_campaign_name || 'utm_campaign',
                            utm_source_name: mapping?.schema_map?.utm_source_name || 'utm_source',
                            // Use timestamp and distinct_id from the DW goal's filter
                            timestamp_field: dwFilter.timestamp_field,
                            distinct_id_field: dwFilter.distinct_id_field,
                        }
                    } else {
                        schemaMap = {
                            utm_campaign_name: 'utm_campaign',
                            utm_source_name: 'utm_source',
                            timestamp_field: undefined,
                            distinct_id_field: undefined,
                        }
                    }
                    return {
                        ...filter,
                        conversion_goal_id: event.id,
                        conversion_goal_name: event.name,
                        schema_map: schemaMap,
                    }
                })
            },
        ],
        // Get mapping for a specific core event (for UI editing)
        getGoalMapping: [
            (s) => [s.goalMappings],
            (mappings: MarketingAnalyticsGoalMapping[]) => {
                return (coreEventId: string): MarketingAnalyticsGoalMapping | undefined => {
                    return mappings.find((m) => m.core_event.id === coreEventId)
                }
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
            // Goal mappings API operations
            addGoalMapping: async ({ coreEventId, schemaMap }) => {
                if (!values.currentTeam) {
                    return
                }
                try {
                    await api.create(`api/environments/${values.currentTeam.id}/marketing_analytics/goal_mappings/`, {
                        core_event_id: coreEventId,
                        schema_map: schemaMap || {},
                    })
                    actions.loadGoalMappings()
                    trackSettingsUpdated()
                } catch {
                    lemonToast.error('Failed to add goal mapping')
                }
            },
            updateGoalMapping: async ({ mappingId, schemaMap }) => {
                if (!values.currentTeam) {
                    return
                }
                try {
                    await api.update(
                        `api/environments/${values.currentTeam.id}/marketing_analytics/goal_mappings/${mappingId}/`,
                        { schema_map: schemaMap }
                    )
                    actions.loadGoalMappings()
                    trackSettingsUpdated()
                } catch {
                    lemonToast.error('Failed to update goal mapping')
                }
            },
            removeGoalMapping: async ({ mappingId }) => {
                if (!values.currentTeam) {
                    return
                }
                try {
                    await api.delete(
                        `api/environments/${values.currentTeam.id}/marketing_analytics/goal_mappings/${mappingId}/`
                    )
                    actions.loadGoalMappings()
                    trackSettingsUpdated()
                } catch {
                    lemonToast.error('Failed to remove goal mapping')
                }
            },
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
    loaders(({ values, actions }) => ({
        marketingAnalyticsConfig: {
            loadMarketingAnalyticsConfig: async () => {
                if (values.currentTeam) {
                    return values.currentTeam.marketing_analytics_config || createEmptyConfig()
                }
                return null
            },
        },
        coreEventsLoader: {
            loadCoreEvents: async () => {
                if (!values.currentTeam) {
                    return []
                }
                try {
                    const response = await api.get(`api/environments/${values.currentTeam.id}/core_events/`)
                    actions.setCoreEvents(response.results || [])
                    return response.results || []
                } catch {
                    return []
                }
            },
        },
        goalMappingsLoader: {
            loadGoalMappings: async () => {
                if (!values.currentTeam) {
                    return []
                }
                try {
                    const response = await api.get(
                        `api/environments/${values.currentTeam.id}/marketing_analytics/goal_mappings/`
                    )
                    actions.setGoalMappings(response.results || [])
                    return response.results || []
                } catch {
                    return []
                }
            },
        },
    })),
    afterMount(({ actions }) => {
        actions.loadMarketingAnalyticsConfig()
        actions.loadCoreEvents()
        actions.loadGoalMappings()
    }),
])
