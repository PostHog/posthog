import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl } from 'kea-router'

import { getDefaultInterval, isValidRelativeOrAbsoluteDate, updateDatesWithInterval, uuid } from 'lib/utils'
import { mapUrlToProvider } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import {
    CompareFilter,
    ConversionGoalFilter,
    CurrencyCode,
    DataWarehouseNode,
    DatabaseSchemaDataWarehouseTable,
    DateRange,
    IntegrationFilter,
    MarketingAnalyticsAggregatedQuery,
    MarketingAnalyticsColumnsSchemaNames,
    NativeMarketingSource,
    NodeKind,
    ProductIntentContext,
    ProductKey,
    SourceMap,
    VALID_NATIVE_MARKETING_SOURCES,
} from '~/queries/schema/schema-general'
import { MARKETING_ANALYTICS_SCHEMA } from '~/queries/schema/schema-general'
import { DataWarehouseSettingsTab, ExternalDataSchemaStatus, ExternalDataSource, IntervalType } from '~/types'
import { ChartDisplayType } from '~/types'

import { defaultConversionGoalFilter } from '../components/settings/constants'
import type { marketingAnalyticsLogicType } from './marketingAnalyticsLogicType'
import { marketingAnalyticsSettingsLogic } from './marketingAnalyticsSettingsLogic'
import { externalAdsCostTile } from './marketingCostTile'
import {
    MarketingDashboardMapper,
    NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS,
    generateUniqueName,
    validColumnsForTiles,
} from './utils'

export enum MarketingSourceStatus {
    Warning = 'Warning',
    Error = 'Error',
    Success = 'Success',
}

export type SourceStatus = ExternalDataSchemaStatus | MarketingSourceStatus

function getSourceStatus(
    source: { id: string; name: string; type: string; prefix?: string },
    nativeSources: ExternalDataSource[],
    validExternalTables: ExternalTable[]
): { status: SourceStatus; message: string } {
    const nativeSource = nativeSources.find((s) => s.id === source.id)
    if (nativeSource) {
        const requiredFields =
            NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS[
                nativeSource.source_type as keyof typeof NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS
            ] || []
        const schemaStatuses = requiredFields
            .map((fieldName) => {
                const schema = nativeSource.schemas?.find((schema) => schema.name === fieldName)
                return schema?.status
            })
            .filter(Boolean)

        if (schemaStatuses.includes(ExternalDataSchemaStatus.Failed)) {
            return { status: ExternalDataSchemaStatus.Failed, message: 'One or more required tables failed to sync' }
        }
        if (schemaStatuses.includes(ExternalDataSchemaStatus.Running)) {
            return {
                status: ExternalDataSchemaStatus.Running,
                message: 'One or more required tables are still syncing',
            }
        }
        if (schemaStatuses.includes(ExternalDataSchemaStatus.Paused)) {
            return { status: ExternalDataSchemaStatus.Paused, message: 'One or more required tables sync is paused' }
        }
        if (schemaStatuses.includes(ExternalDataSchemaStatus.Cancelled)) {
            return {
                status: ExternalDataSchemaStatus.Cancelled,
                message: 'One or more required tables sync is cancelled',
            }
        }
        if (
            schemaStatuses.length === requiredFields.length &&
            schemaStatuses.every((status) => status === ExternalDataSchemaStatus.Completed)
        ) {
            return {
                status: ExternalDataSchemaStatus.Completed,
                message: 'Ready to use! All required fields have synced.',
            }
        }
        return { status: MarketingSourceStatus.Warning, message: 'Some required tables need to be synced' }
    }

    const externalTable = validExternalTables.find((t) => t.source_map_id === source.id)
    if (externalTable) {
        // Prioritize mapping status over sync status
        const hasMapping = externalTable.source_map && Object.keys(externalTable.source_map).length > 0

        if (!hasMapping) {
            return { status: MarketingSourceStatus.Warning, message: 'Needs column mapping' }
        }

        // For sources with schema_status (managed sources like BigQuery)
        if (externalTable.schema_status) {
            if (externalTable.schema_status === ExternalDataSchemaStatus.Completed) {
                return { status: ExternalDataSchemaStatus.Completed, message: 'Ready to use' }
            }
            if (externalTable.schema_status === ExternalDataSchemaStatus.Failed) {
                return { status: ExternalDataSchemaStatus.Failed, message: 'Table sync failed' }
            }
            if (externalTable.schema_status === ExternalDataSchemaStatus.Running) {
                return { status: ExternalDataSchemaStatus.Running, message: 'Table is syncing' }
            }
            if (externalTable.schema_status === ExternalDataSchemaStatus.Paused) {
                return { status: ExternalDataSchemaStatus.Paused, message: 'Table sync is paused' }
            }
            if (externalTable.schema_status === ExternalDataSchemaStatus.Cancelled) {
                return { status: ExternalDataSchemaStatus.Cancelled, message: 'Table sync is cancelled' }
            }
        }

        // For self-managed sources having a mapping means it's ready
        return { status: ExternalDataSchemaStatus.Completed, message: 'Ready to use' }
    }

    return { status: MarketingSourceStatus.Error, message: 'Unknown source status' }
}

export type ExternalTable = {
    name: string
    source_type: string
    id: string
    source_map_id: string
    source_prefix: string
    columns: { name: string; type: string }[]
    url_pattern: string
    sourceUrl: string
    external_type: DataWarehouseSettingsTab
    source_map: SourceMap | null
    schema_name: string
    dw_source_type: string
    schema_status?: string
}

export type NativeSource = {
    source: ExternalDataSource
    tables: DatabaseSchemaDataWarehouseTable[]
}

export interface DateFilterState extends DateRange {
    interval: IntervalType
}

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
const persistConfig = { persist: true, prefix: `${teamId}__` }

const INITIAL_DATE_FROM = '-7d' as string | null
const INITIAL_DATE_TO = null as string | null
const INITIAL_INTERVAL = getDefaultInterval(INITIAL_DATE_FROM, INITIAL_DATE_TO)

export const marketingAnalyticsLogic = kea<marketingAnalyticsLogicType>([
    path(['scenes', 'webAnalytics', 'marketingAnalyticsLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['baseCurrency'],
            marketingAnalyticsSettingsLogic,
            ['sources_map', 'conversion_goals'],
            dataWarehouseSettingsLogic,
            ['dataWarehouseTables', 'dataWarehouseSourcesLoading', 'dataWarehouseSources'],
        ],
        actions: [
            dataWarehouseSettingsLogic,
            ['loadSources', 'loadSourcesSuccess'],
            dataNodeCollectionLogic({ key: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }),
            ['reloadAll'],
            marketingAnalyticsSettingsLogic,
            ['addOrUpdateConversionGoal'],
            teamLogic,
            ['addProductIntent'],
        ],
    })),
    actions({
        // Low-level state setters (used by listeners)
        setDraftConversionGoal: (goal: ConversionGoalFilter | null) => ({ goal }),
        setConversionGoalInput: (goal: ConversionGoalFilter) => ({ goal }),

        // User intent actions (used by components)
        applyConversionGoal: true,
        saveConversionGoal: true,
        clearConversionGoal: true,
        loadConversionGoal: (goal: ConversionGoalFilter) => ({ goal }),

        setCompareFilter: (compareFilter: CompareFilter) => ({ compareFilter }),
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setInterval: (interval: IntervalType) => ({ interval }),
        setDatesAndInterval: (dateFrom: string | null, dateTo: string | null, interval: IntervalType) => ({
            dateFrom,
            dateTo,
            interval,
        }),
        setIntegrationFilter: (integrationFilter: IntegrationFilter) => ({ integrationFilter }),
        // Internal action for URL sync - updates state without triggering actionToUrl
        syncFromUrl: (params: {
            dateFrom?: string | null
            dateTo?: string | null
            interval?: IntervalType
            compare?: boolean
            compare_to?: string
            integrationSourceIds?: string[]
            chartDisplayType?: ChartDisplayType
            tileColumnSelection?: string
        }) => ({ params }),
        showColumnConfigModal: true,
        hideColumnConfigModal: true,
        showConversionGoalModal: true,
        hideConversionGoalModal: true,
        setChartDisplayType: (chartDisplayType: ChartDisplayType) => ({ chartDisplayType }),
        setTileColumnSelection: (column: validColumnsForTiles) => ({ column }),
        setInitialized: true,
    }),
    reducers({
        initialized: [
            false,
            {
                setInitialized: () => true,
            },
        ],
        draftConversionGoal: [
            null as ConversionGoalFilter | null,
            {
                setDraftConversionGoal: (_, { goal }) => goal,
            },
        ],
        conversionGoalInput: [
            {
                ...defaultConversionGoalFilter,
                conversion_goal_id: uuid(),
                conversion_goal_name: '',
            } as ConversionGoalFilter,
            {
                setConversionGoalInput: (_, { goal }) => goal,
            },
        ],
        compareFilter: [
            { compare: true } as CompareFilter,
            persistConfig,
            {
                setCompareFilter: (_, { compareFilter }) => compareFilter,
                syncFromUrl: (state, { params }) => {
                    if (params.compare === undefined && params.compare_to === undefined) {
                        return state
                    }
                    return {
                        ...state,
                        ...(params.compare !== undefined ? { compare: params.compare } : {}),
                        ...(params.compare_to !== undefined ? { compare_to: params.compare_to } : {}),
                    }
                },
            },
        ],
        integrationFilter: [
            { integrationSourceIds: [] } as IntegrationFilter,
            persistConfig,
            {
                setIntegrationFilter: (_, { integrationFilter }) => integrationFilter,
                syncFromUrl: (state, { params }) =>
                    params.integrationSourceIds ? { integrationSourceIds: params.integrationSourceIds } : state,
            },
        ],
        dateFilter: [
            {
                dateFrom: INITIAL_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
                interval: INITIAL_INTERVAL,
            },
            persistConfig,
            {
                setDates: (_, { dateFrom, dateTo }) => {
                    if (dateTo && !isValidRelativeOrAbsoluteDate(dateTo)) {
                        dateTo = INITIAL_DATE_TO
                    }
                    if (dateFrom && !isValidRelativeOrAbsoluteDate(dateFrom)) {
                        dateFrom = INITIAL_DATE_FROM
                    }
                    return {
                        dateFrom,
                        dateTo,
                        interval: getDefaultInterval(dateFrom, dateTo),
                    }
                },
                setInterval: (state, { interval }) => {
                    const { dateFrom, dateTo } = updateDatesWithInterval(interval, state.dateFrom, state.dateTo)
                    return {
                        dateFrom,
                        dateTo,
                        interval,
                    }
                },
                setDatesAndInterval: (_, { dateFrom, dateTo, interval }) => {
                    if (!dateFrom && !dateTo) {
                        dateFrom = INITIAL_DATE_FROM
                        dateTo = INITIAL_DATE_TO
                    }
                    if (dateTo && !isValidRelativeOrAbsoluteDate(dateTo)) {
                        dateTo = INITIAL_DATE_TO
                    }
                    if (dateFrom && !isValidRelativeOrAbsoluteDate(dateFrom)) {
                        dateFrom = INITIAL_DATE_FROM
                    }
                    return {
                        dateFrom,
                        dateTo,
                        interval: interval || getDefaultInterval(dateFrom, dateTo),
                    }
                },
                syncFromUrl: (state, { params }) => {
                    if (params.dateFrom === undefined && params.dateTo === undefined && params.interval === undefined) {
                        return state
                    }
                    const dateFrom = params.dateFrom ?? state.dateFrom
                    const dateTo = params.dateTo ?? state.dateTo
                    const interval = params.interval ?? state.interval
                    return { dateFrom, dateTo, interval }
                },
            },
        ],
        columnConfigModalVisible: [
            false,
            {
                showColumnConfigModal: () => true,
                hideColumnConfigModal: () => false,
            },
        ],
        conversionGoalModalVisible: [
            false,
            {
                showConversionGoalModal: () => true,
                hideConversionGoalModal: () => false,
            },
        ],
        chartDisplayType: [
            ChartDisplayType.ActionsAreaGraph as ChartDisplayType,
            persistConfig,
            {
                setChartDisplayType: (_, { chartDisplayType }) => chartDisplayType,
                syncFromUrl: (state, { params }) =>
                    params.chartDisplayType !== undefined ? params.chartDisplayType : state,
            },
        ],
        tileColumnSelection: [
            MarketingAnalyticsColumnsSchemaNames.Cost as validColumnsForTiles,
            persistConfig,
            {
                setTileColumnSelection: (_, { column }) => column,
                syncFromUrl: (state, { params }) =>
                    params.tileColumnSelection !== undefined
                        ? (params.tileColumnSelection as validColumnsForTiles)
                        : state,
            },
        ],
    }),
    selectors({
        validSourcesMap: [
            (s) => [s.sources_map],
            (sources_map) => {
                if (!sources_map || Object.keys(sources_map).length === 0) {
                    return null
                }

                const validSourcesMap = sources_map
                const requiredColumns = Object.values(MarketingAnalyticsColumnsSchemaNames).filter(
                    (column_name: MarketingAnalyticsColumnsSchemaNames) =>
                        MARKETING_ANALYTICS_SCHEMA[column_name].required
                )

                requiredColumns.forEach((column_name: MarketingAnalyticsColumnsSchemaNames) => {
                    Object.entries(validSourcesMap).forEach(([tableId, fieldMapping]: [string, any]) => {
                        const mapping = fieldMapping?.[column_name]
                        const isValidMapping = mapping && typeof mapping === 'string' && mapping.trim() !== ''

                        if (!isValidMapping) {
                            delete validSourcesMap[tableId]
                        }
                    })
                })

                if (Object.keys(validSourcesMap).length === 0) {
                    return null
                }
                return validSourcesMap
            },
        ],
        externalTables: [
            (s) => [s.dataWarehouseTables, s.sources_map, s.dataWarehouseSources],
            (dataWarehouseTables, sources_map, dataWarehouseSources) => {
                const externalTables: ExternalTable[] = []
                if (dataWarehouseTables?.length) {
                    dataWarehouseTables.forEach((table) => {
                        if (!table.fields) {
                            return
                        }
                        const dataWarehouseSource = dataWarehouseSources?.results.find((source: any) =>
                            source.schemas
                                .map((schema: DatabaseSchemaDataWarehouseTable) => schema.id)
                                .includes(table.schema?.id)
                        )
                        const isDataWarehouse = !!table.schema
                        const tableType = isDataWarehouse
                            ? DataWarehouseSettingsTab.Managed
                            : DataWarehouseSettingsTab.SelfManaged
                        const sourceMap = sources_map?.[table.schema?.id || ''] ?? sources_map?.[table.id] ?? null

                        externalTables.push({
                            ...table,
                            name: table.name,
                            source_type: table.source?.source_type || mapUrlToProvider(table.url_pattern),
                            source_map_id: table.schema?.id || table.source?.id || table.id,
                            source_prefix: table.source?.prefix || '',
                            columns: Object.keys(table.fields).map((field) => ({
                                name: table.fields[field].hogql_value,
                                type: table.fields[field].type,
                            })),
                            sourceUrl: urls.dataWarehouseSource(
                                `${tableType}-${dataWarehouseSource?.id || table.source?.id || table.id}`
                            ),
                            external_type: tableType,
                            source_map: sourceMap,
                            schema_name: table.schema?.name || table.name,
                            dw_source_type: tableType,
                            schema_status: table.schema?.status,
                        })
                    })
                }

                return externalTables
            },
        ],
        validExternalTables: [
            (s) => [s.externalTables, s.validSourcesMap],
            (externalTables, validSourcesMap: Record<string, SourceMap> | null): ExternalTable[] => {
                if (!validSourcesMap || Object.keys(validSourcesMap).length === 0) {
                    return []
                }

                return externalTables.filter((table) => validSourcesMap[table.source_map_id])
            },
        ],
        nativeSources: [
            (s) => [s.dataWarehouseSources],
            (dataWarehouseSources): ExternalDataSource[] => {
                const nativeSources =
                    dataWarehouseSources?.results.filter((source) =>
                        VALID_NATIVE_MARKETING_SOURCES.includes(source.source_type as NativeMarketingSource)
                    ) ?? []
                nativeSources.forEach((source) => {
                    const neededFieldsWithSync =
                        NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS[source.source_type as NativeMarketingSource]
                    source.schemas = source.schemas.filter((schema) => neededFieldsWithSync.includes(schema.name))
                })
                return nativeSources
            },
        ],
        validNativeSources: [
            (s) => [s.nativeSources, s.dataWarehouseTables],
            (nativeSources, dataWarehouseTables): NativeSource[] => {
                return nativeSources.reduce((validNativeSources: NativeSource[], source) => {
                    const requiredFields =
                        NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS[source.source_type as NativeMarketingSource] || []

                    const syncingSchemas = requiredFields.filter((fieldName) => {
                        const schema = source.schemas?.find((s) => s.name === fieldName)
                        return schema?.should_sync ?? false
                    })

                    const isValid = requiredFields.length > 0 && syncingSchemas.length === requiredFields.length

                    if (isValid) {
                        const tables =
                            dataWarehouseTables?.filter((table) =>
                                source.schemas.some((schema) => schema.id === table.schema?.id)
                            ) ?? []

                        validNativeSources.push({
                            source,
                            tables,
                        })
                    }
                    return validNativeSources
                }, [])
            },
        ],
        uniqueConversionGoalName: [
            (s) => [s.conversionGoalInput, s.conversion_goals],
            (conversionGoalInput: ConversionGoalFilter | null, conversion_goals: ConversionGoalFilter[]): string => {
                const baseName = conversionGoalInput?.conversion_goal_name || conversionGoalInput?.name || 'No name'
                const existingNames = conversion_goals.map((goal) => goal.conversion_goal_name)
                return generateUniqueName(baseName, existingNames)
            },
        ],
        loading: [
            (s) => [s.dataWarehouseSourcesLoading],
            (dataWarehouseSourcesLoading: boolean) => dataWarehouseSourcesLoading,
        ],
        allAvailableSources: [
            (s) => [s.validExternalTables, s.validNativeSources],
            (validExternalTables: ExternalTable[], validNativeSources: NativeSource[]) => {
                const sources: Array<{ id: string; name: string; type: string; source_type: string; prefix?: string }> =
                    []

                validNativeSources.forEach((nativeSource) => {
                    sources.push({
                        id: nativeSource.source.id,
                        name: nativeSource.source.source_type,
                        type: 'native',
                        source_type: nativeSource.source.source_type,
                        prefix: nativeSource.source.prefix ?? undefined,
                    })
                })

                validExternalTables.forEach((table) => {
                    sources.push({
                        id: table.source_map_id,
                        name: table.schema_name,
                        type: table.external_type,
                        source_type: table.source_type,
                        prefix: table.source_prefix,
                    })
                })

                return sources
            },
        ],
        allAvailableSourcesWithStatus: [
            (s) => [s.allAvailableSources, s.nativeSources, s.validExternalTables],
            (allAvailableSources, nativeSources, validExternalTables) => {
                return allAvailableSources.map((source) => {
                    const status = getSourceStatus(source, nativeSources, validExternalTables)
                    return {
                        ...source,
                        status: status.status,
                        statusMessage: status.message,
                    }
                })
            },
        ],
        allExternalTablesWithStatus: [
            (s) => [s.externalTables, s.nativeSources],
            (externalTables, nativeSources) => {
                // Filter out tables that belong to native sources (to avoid duplicates)
                // Only include BigQuery, self-managed, and other non-native sources
                // For example a native source could have multiple external tables.
                const nonNativeTables = externalTables.filter(
                    (table) => !VALID_NATIVE_MARKETING_SOURCES.includes(table.source_type as NativeMarketingSource)
                )

                // Get all non-native external tables with status
                const externalTablesWithStatus = nonNativeTables.map((table) => {
                    const status = getSourceStatus(
                        {
                            id: table.source_map_id,
                            name: table.schema_name,
                            type: table.external_type,
                            prefix: table.source_prefix,
                        },
                        [],
                        nonNativeTables
                    )
                    return {
                        ...table,
                        status: status.status,
                        statusMessage: status.message,
                    }
                })

                // Get all native sources with status and convert to ExternalTable format
                const nativeSourcesAsExternalTables = nativeSources.map((source) => {
                    const status = getSourceStatus(
                        { id: source.id, name: source.source_type, type: 'native', prefix: source.prefix ?? undefined },
                        nativeSources,
                        []
                    )

                    // Convert native source to ExternalTable format for unified handling
                    return {
                        ...source,
                        name: source.prefix || source.source_type,
                        source_type: source.source_type,
                        id: source.id,
                        source_map_id: source.id,
                        source_prefix: source.prefix || '',
                        columns: [],
                        url_pattern: '',
                        sourceUrl: '',
                        external_type: 'native' as any,
                        source_map: null,
                        schema_name: source.source_type,
                        dw_source_type: source.source_type,
                        status: status.status,
                        statusMessage: status.message,
                        isNativeSource: true,
                    } as ExternalTable & { status: SourceStatus; statusMessage: string; isNativeSource?: boolean }
                })

                const result = [...nativeSourcesAsExternalTables, ...externalTablesWithStatus]
                return result
            },
        ],
        createMarketingDataWarehouseNodes: [
            (s) => [
                s.validExternalTables,
                s.baseCurrency,
                s.validNativeSources,
                s.tileColumnSelection,
                s.integrationFilter,
            ],
            (
                validExternalTables: ExternalTable[],
                baseCurrency: CurrencyCode,
                validNativeSources: NativeSource[],
                tileColumnSelection: validColumnsForTiles,
                integrationFilter: IntegrationFilter
            ): DataWarehouseNode[] => {
                const selectedIds = integrationFilter.integrationSourceIds || []
                const hasFilter = selectedIds.length > 0

                const filteredExternalTables = hasFilter
                    ? validExternalTables.filter((table) => selectedIds.includes(table.source_map_id))
                    : validExternalTables

                const filteredNativeSources = hasFilter
                    ? validNativeSources.filter((source) => selectedIds.includes(source.source.id))
                    : validNativeSources

                const nonNativeNodeList: DataWarehouseNode[] = filteredExternalTables
                    .map((table) => externalAdsCostTile(table, baseCurrency, tileColumnSelection))
                    .filter(Boolean) as DataWarehouseNode[]

                const nativeNodeList: DataWarehouseNode[] = filteredNativeSources
                    .map((source) => MarketingDashboardMapper(source, tileColumnSelection, baseCurrency))
                    .filter(Boolean) as DataWarehouseNode[]

                return [...nativeNodeList, ...nonNativeNodeList]
            },
        ],
        overviewQuery: [
            (s) => [s.dateFilter, s.compareFilter, s.draftConversionGoal, s.integrationFilter],
            (dateFilter, compareFilter, draftConversionGoal, integrationFilter): MarketingAnalyticsAggregatedQuery => ({
                kind: NodeKind.MarketingAnalyticsAggregatedQuery,
                dateRange: {
                    date_from: dateFilter.dateFrom,
                    date_to: dateFilter.dateTo,
                },
                compareFilter,
                properties: [],
                draftConversionGoal: draftConversionGoal || undefined,
                integrationFilter,
            }),
        ],
    }),
    actionToUrl(({ values }) => {
        const buildUrl = (): [string, string] => {
            const searchParams = new URLSearchParams()

            // Date filters
            if (values.dateFilter.dateFrom) {
                searchParams.set('date_from', values.dateFilter.dateFrom)
            }
            if (values.dateFilter.dateTo) {
                searchParams.set('date_to', values.dateFilter.dateTo)
            }
            if (values.dateFilter.interval) {
                searchParams.set('interval', values.dateFilter.interval)
            }

            // Compare filter
            if (values.compareFilter?.compare !== undefined) {
                searchParams.set('compare', values.compareFilter.compare ? 'true' : 'false')
            }
            if (values.compareFilter?.compare_to) {
                searchParams.set('compare_to', values.compareFilter.compare_to)
            }

            // Integration filter
            if (values.integrationFilter?.integrationSourceIds?.length) {
                searchParams.set('integration_sources', values.integrationFilter.integrationSourceIds.join(','))
            }

            // Chart display type
            if (values.chartDisplayType) {
                searchParams.set('chart_display_type', values.chartDisplayType)
            }

            // Tile column selection
            if (values.tileColumnSelection) {
                searchParams.set('tile_column', values.tileColumnSelection)
            }

            return [window.location.pathname, searchParams.toString()]
        }

        return {
            setDates: buildUrl,
            setInterval: buildUrl,
            setDatesAndInterval: buildUrl,
            setCompareFilter: buildUrl,
            setIntegrationFilter: buildUrl,
            setChartDisplayType: buildUrl,
            setTileColumnSelection: buildUrl,
            // Note: syncFromUrl is NOT mapped here - it's only for receiving URL changes
        }
    }),
    // Note: We don't use urlToAction here to avoid sync loops.
    // URL params are read once on mount in afterMount instead.
    listeners(({ actions, values }) => {
        const trackDashboardInteraction = (): void => {
            // Only track after initialization to avoid tracking initial render/setup
            if (!values.initialized) {
                return
            }
            actions.addProductIntent({
                product_type: ProductKey.MARKETING_ANALYTICS,
                intent_context: ProductIntentContext.MARKETING_ANALYTICS_DASHBOARD_INTERACTION,
            })
        }

        return {
            // Track dashboard interactions for filters and chart controls
            setDates: trackDashboardInteraction,
            setInterval: trackDashboardInteraction,
            setCompareFilter: trackDashboardInteraction,
            setIntegrationFilter: trackDashboardInteraction,
            setChartDisplayType: trackDashboardInteraction,
            setTileColumnSelection: trackDashboardInteraction,
            reloadAll: trackDashboardInteraction,
            applyConversionGoal: [
                () => {
                    const goal = {
                        ...values.conversionGoalInput,
                        conversion_goal_name: values.uniqueConversionGoalName,
                    }
                    actions.setDraftConversionGoal(goal)
                    actions.setConversionGoalInput(goal)
                    actions.hideConversionGoalModal()
                },
                trackDashboardInteraction,
            ],
            saveConversionGoal: [
                () => {
                    // First save the draft goal to the conversion_goals list
                    if (values.draftConversionGoal) {
                        actions.addOrUpdateConversionGoal(values.draftConversionGoal)
                    }
                    // Then clear the draft and input state (resets UI)
                    actions.setDraftConversionGoal(null)
                    actions.setConversionGoalInput({
                        ...defaultConversionGoalFilter,
                        conversion_goal_id: uuid(),
                        conversion_goal_name: '',
                    })
                    actions.hideConversionGoalModal()
                },
                trackDashboardInteraction,
            ],
            clearConversionGoal: [
                () => {
                    actions.setDraftConversionGoal(null)
                    actions.setConversionGoalInput({
                        ...defaultConversionGoalFilter,
                        conversion_goal_id: uuid(),
                        conversion_goal_name: '',
                    })
                    actions.hideConversionGoalModal()
                },
                trackDashboardInteraction,
            ],
            loadConversionGoal: ({ goal }) => {
                // Generate new ID so changes are always detected when applying
                actions.setConversionGoalInput({
                    ...goal,
                    conversion_goal_id: uuid(),
                })
            },
            loadSourcesSuccess: () => {
                // Clean up integrationFilter if it contains IDs of sources that no longer exist
                const currentFilter = values.integrationFilter
                if (currentFilter.integrationSourceIds && currentFilter.integrationSourceIds.length > 0) {
                    const availableSourceIds = values.allAvailableSources.map((s) => s.id)
                    const validFilterIds = currentFilter.integrationSourceIds.filter((id) =>
                        availableSourceIds.includes(id)
                    )

                    if (validFilterIds.length !== currentFilter.integrationSourceIds.length) {
                        actions.setIntegrationFilter({ integrationSourceIds: validFilterIds })
                    }
                }

                // Reload all queries to reflect the updated sources
                actions.reloadAll()

                // Mark as initialized after initial data load to enable interaction tracking
                if (!values.initialized) {
                    actions.setInitialized()
                }
            },
        }
    }),
    afterMount(({ actions }) => {
        // Read URL params on initial mount (one-time sync from URL)
        const searchParams = new URLSearchParams(window.location.search)
        const params: Parameters<typeof actions.syncFromUrl>[0] = {}

        const dateFrom = searchParams.get('date_from')
        if (dateFrom) {
            params.dateFrom = dateFrom
        }
        const dateTo = searchParams.get('date_to')
        if (dateTo) {
            params.dateTo = dateTo
        }
        const interval = searchParams.get('interval') as IntervalType | null
        if (interval) {
            params.interval = interval
        }
        const compare = searchParams.get('compare')
        if (compare !== null) {
            params.compare = compare === 'true'
        }
        const compareTo = searchParams.get('compare_to')
        if (compareTo) {
            params.compare_to = compareTo
        }
        const integrationSources = searchParams.get('integration_sources')
        if (integrationSources) {
            params.integrationSourceIds = integrationSources.split(',').filter(Boolean)
        }
        const chartDisplayType = searchParams.get('chart_display_type') as ChartDisplayType | null
        if (chartDisplayType && Object.values(ChartDisplayType).includes(chartDisplayType)) {
            params.chartDisplayType = chartDisplayType
        }
        const tileColumn = searchParams.get('tile_column')
        if (tileColumn) {
            params.tileColumnSelection = tileColumn
        }

        // Apply URL params if any were found
        if (Object.keys(params).length > 0) {
            actions.syncFromUrl(params)
        }

        actions.loadSources(null)
    }),
])
