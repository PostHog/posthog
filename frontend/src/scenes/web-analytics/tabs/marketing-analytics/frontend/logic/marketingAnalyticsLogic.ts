import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'

import { getDefaultInterval, isValidRelativeOrAbsoluteDate, updateDatesWithInterval, uuid } from 'lib/utils'
import { mapUrlToProvider } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

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
    NodeKind,
    SourceMap,
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
    NativeMarketingSource,
    VALID_NATIVE_MARKETING_SOURCES,
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
    })),
    actions({
        setDraftConversionGoal: (goal: ConversionGoalFilter | null) => ({ goal }),
        setConversionGoalInput: (goal: ConversionGoalFilter) => ({ goal }),
        resetConversionGoalInput: () => true,
        saveDraftConversionGoal: () => true,
        setCompareFilter: (compareFilter: CompareFilter) => ({ compareFilter }),
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setInterval: (interval: IntervalType) => ({ interval }),
        setDatesAndInterval: (dateFrom: string | null, dateTo: string | null, interval: IntervalType) => ({
            dateFrom,
            dateTo,
            interval,
        }),
        setIntegrationFilter: (integrationFilter: IntegrationFilter) => ({ integrationFilter }),
        showColumnConfigModal: true,
        hideColumnConfigModal: true,
        setChartDisplayType: (chartDisplayType: ChartDisplayType) => ({ chartDisplayType }),
        setTileColumnSelection: (column: validColumnsForTiles) => ({ column }),
    }),
    reducers({
        draftConversionGoal: [
            null as ConversionGoalFilter | null,
            {
                setDraftConversionGoal: (_, { goal }) => goal,
            },
        ],
        conversionGoalInput: [
            (() => {
                return {
                    ...defaultConversionGoalFilter,
                    conversion_goal_id: uuid(),
                    conversion_goal_name: '',
                }
            })() as ConversionGoalFilter,
            {
                setConversionGoalInput: (_, { goal }) => goal,
                resetConversionGoalInput: () => {
                    return {
                        ...defaultConversionGoalFilter,
                        conversion_goal_id: uuid(),
                        conversion_goal_name: '',
                    }
                },
            },
        ],
        compareFilter: [
            { compare: true } as CompareFilter,
            persistConfig,
            {
                setCompareFilter: (_, { compareFilter }) => compareFilter,
            },
        ],
        integrationFilter: [
            { integrationSourceIds: [] } as IntegrationFilter,
            persistConfig,
            {
                setIntegrationFilter: (_, { integrationFilter }) => integrationFilter,
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
            },
        ],
        columnConfigModalVisible: [
            false,
            {
                showColumnConfigModal: () => true,
                hideColumnConfigModal: () => false,
            },
        ],
        chartDisplayType: [
            ChartDisplayType.ActionsAreaGraph as ChartDisplayType,
            persistConfig,
            {
                setChartDisplayType: (_, { chartDisplayType }) => chartDisplayType,
            },
        ],
        tileColumnSelection: [
            MarketingAnalyticsColumnsSchemaNames.Cost as validColumnsForTiles,
            persistConfig,
            {
                setTileColumnSelection: (_, { column }) => column,
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
                        prefix: nativeSource.source.prefix,
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
        nativeSourcesWithStatus: [
            (s) => [s.nativeSources],
            (nativeSources) => {
                return nativeSources.map((source) => {
                    const status = getSourceStatus(
                        { id: source.id, name: source.source_type, type: 'native', prefix: source.prefix },
                        nativeSources,
                        []
                    )
                    return {
                        ...source,
                        status: status.status,
                        statusMessage: status.message,
                    }
                })
            },
        ],
        externalTablesWithStatus: [
            (s) => [s.externalTables],
            (externalTables) => {
                return externalTables.map((table) => {
                    const status = getSourceStatus(
                        {
                            id: table.source_map_id,
                            name: table.schema_name,
                            type: table.external_type,
                            prefix: table.source_prefix,
                        },
                        [],
                        externalTables
                    )
                    return {
                        ...table,
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
                        { id: source.id, name: source.source_type, type: 'native', prefix: source.prefix },
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
    actionToUrl(({ values }) => ({
        setChartDisplayType: () => {
            const searchParams = new URLSearchParams(window.location.search)
            searchParams.set('chart_display_type', values.chartDisplayType)
            return [window.location.pathname, searchParams.toString()]
        },
    })),
    urlToAction(({ actions }) => ({
        '*': (_, searchParams) => {
            const chartDisplayType = searchParams.chart_display_type as ChartDisplayType | undefined
            if (chartDisplayType && Object.values(ChartDisplayType).includes(chartDisplayType)) {
                actions.setChartDisplayType(chartDisplayType)
            }
        },
    })),
    listeners(({ actions }) => ({
        saveDraftConversionGoal: () => {
            // Create a new local conversion goal with new id
            actions.resetConversionGoalInput()
        },
        resetConversionGoalInput: () => {
            // Clear the draft goal when resetting local goal
            actions.setDraftConversionGoal(null)
        },
    })),
])
