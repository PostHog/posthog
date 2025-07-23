import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { mapUrlToProvider } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    CurrencyCode,
    DatabaseSchemaDataWarehouseTable,
    DataWarehouseNode,
    SourceMap,
    ConversionGoalFilter,
    MarketingAnalyticsOrderBy,
    MarketingAnalyticsColumnsSchemaNames,
    CompareFilter,
} from '~/queries/schema/schema-general'
import { DataWarehouseSettingsTab, ExternalDataSource, IntervalType, PipelineNodeTab, PipelineStage } from '~/types'

import { MARKETING_ANALYTICS_SCHEMA } from '~/queries/schema/schema-general'
import type { marketingAnalyticsLogicType } from './marketingAnalyticsLogicType'
import { marketingAnalyticsSettingsLogic } from './marketingAnalyticsSettingsLogic'
import { externalAdsCostTile } from './marketingCostTile'
import {
    MarketingDashboardMapper,
    NativeMarketingSource,
    NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS,
    VALID_NATIVE_MARKETING_SOURCES,
} from './utils'
import { getDefaultInterval, isValidRelativeOrAbsoluteDate, updateDatesWithInterval } from 'lib/utils'

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
}

export type NativeSource = {
    source: ExternalDataSource
    tables: DatabaseSchemaDataWarehouseTable[]
}

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
const persistConfig = { persist: true, prefix: `${teamId}__` }

const INITIAL_DATE_FROM = '-7d' as string | null
const INITIAL_DATE_TO = null as string | null
const INITIAL_INTERVAL = getDefaultInterval(INITIAL_DATE_FROM, INITIAL_DATE_TO)

export const marketingAnalyticsLogic = kea<marketingAnalyticsLogicType>([
    path(['scenes', 'webAnalytics', 'marketingAnalyticsLogic']),
    actions({
        setMarketingAnalyticsOrderBy: (orderBy: number, direction: 'ASC' | 'DESC') => ({ orderBy, direction }),
        clearMarketingAnalyticsOrderBy: () => true,
        setDynamicConversionGoal: (goal: ConversionGoalFilter | null) => ({ goal }),
        setCompareFilter: (compareFilter: CompareFilter) => ({ compareFilter }),
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setInterval: (interval: IntervalType) => ({ interval }),
        setDatesAndInterval: (dateFrom: string | null, dateTo: string | null, interval: IntervalType) => ({
            dateFrom,
            dateTo,
            interval,
        }),
    }),
    reducers({
        marketingAnalyticsOrderBy: [
            null as MarketingAnalyticsOrderBy | null,
            {
                setMarketingAnalyticsOrderBy: (_, { orderBy, direction }) => [orderBy, direction],
                clearMarketingAnalyticsOrderBy: () => null,
            },
        ],
        dynamicConversionGoal: [
            null as ConversionGoalFilter | null,
            {
                setDynamicConversionGoal: (_, { goal }) => goal,
            },
        ],
        compareFilter: [
            { compare: true } as CompareFilter,
            persistConfig,
            {
                setCompareFilter: (_, { compareFilter }) => compareFilter,
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
                setDates: (_, { dateTo, dateFrom }) => {
                    if (dateTo && !isValidRelativeOrAbsoluteDate(dateTo)) {
                        dateTo = INITIAL_DATE_TO
                    }
                    if (dateFrom && !isValidRelativeOrAbsoluteDate(dateFrom)) {
                        dateFrom = INITIAL_DATE_FROM
                    }
                    return {
                        dateTo,
                        dateFrom,
                        interval: getDefaultInterval(dateFrom, dateTo),
                    }
                },
                setInterval: ({ dateFrom: oldDateFrom, dateTo: oldDateTo }, { interval }) => {
                    const { dateFrom, dateTo } = updateDatesWithInterval(interval, oldDateFrom, oldDateTo)
                    return {
                        dateTo,
                        dateFrom,
                        interval,
                    }
                },
                setDatesAndInterval: (_, { dateTo, dateFrom, interval }) => {
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
                        dateTo,
                        dateFrom,
                        interval: interval || getDefaultInterval(dateFrom, dateTo),
                    }
                },
            },
        ],
    }),
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
    selectors({
        validSourcesMap: [
            (s) => [s.sources_map],
            (sources_map) => {
                if (!sources_map || Object.keys(sources_map).length === 0) {
                    return null
                }

                const validSourcesMap = sources_map

                Object.values(MarketingAnalyticsColumnsSchemaNames)
                    .filter(
                        (column_name: MarketingAnalyticsColumnsSchemaNames) =>
                            MARKETING_ANALYTICS_SCHEMA[column_name].required
                    )
                    .forEach((column_name: MarketingAnalyticsColumnsSchemaNames) => {
                        Object.entries(validSourcesMap).forEach(([tableId, fieldMapping]: [string, any]) => {
                            if (fieldMapping && !fieldMapping[column_name]) {
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
                            sourceUrl: urls.pipelineNode(
                                PipelineStage.Source,
                                `${tableType}-${dataWarehouseSource?.id || table.source?.id || table.id}`,
                                isDataWarehouse ? PipelineNodeTab.Schemas : PipelineNodeTab.SourceConfiguration
                            ),
                            external_type: tableType,
                            source_map: sourceMap,
                            schema_name: table.schema?.name || table.name,
                            dw_source_type: tableType,
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
                    if (
                        source.schemas.length ===
                        NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS[source.source_type as NativeMarketingSource].length
                    ) {
                        validNativeSources.push({
                            source,
                            tables:
                                dataWarehouseTables?.filter((table) =>
                                    source.schemas.some((schema) => schema.id === table.schema?.id)
                                ) ?? [],
                        })
                    }
                    return validNativeSources
                }, [])
            },
        ],
        loading: [
            (s) => [s.dataWarehouseSourcesLoading],
            (dataWarehouseSourcesLoading: boolean) => dataWarehouseSourcesLoading,
        ],
        createMarketingDataWarehouseNodes: [
            (s) => [s.validExternalTables, s.baseCurrency, s.validNativeSources],
            (
                validExternalTables: ExternalTable[],
                baseCurrency: CurrencyCode,
                validNativeSources: NativeSource[]
            ): DataWarehouseNode[] => {
                const nonNativeNodeList: DataWarehouseNode[] = validExternalTables
                    .map((table) => externalAdsCostTile(table, baseCurrency))
                    .filter(Boolean) as DataWarehouseNode[]

                const nativeNodeList: DataWarehouseNode[] = validNativeSources
                    .map((source) => MarketingDashboardMapper(source))
                    .filter(Boolean) as DataWarehouseNode[]

                return [...nativeNodeList, ...nonNativeNodeList]
            },
        ],
    }),
    actionToUrl(() => ({
        setMarketingAnalyticsOrderBy: ({ orderBy, direction }) => {
            const searchParams = new URLSearchParams(window.location.search)
            if (orderBy !== null && direction) {
                searchParams.set('sort_field', orderBy.toString())
                searchParams.set('sort_direction', direction)
            } else {
                searchParams.delete('sort_field')
                searchParams.delete('sort_direction')
            }
            return [window.location.pathname, searchParams.toString()]
        },
        clearMarketingAnalyticsOrderBy: () => {
            const searchParams = new URLSearchParams(window.location.search)
            searchParams.delete('sort_field')
            searchParams.delete('sort_direction')
            return [window.location.pathname, searchParams.toString()]
        },
    })),
    urlToAction(({ actions, values }) => ({
        '*': (_, searchParams) => {
            const sortField = searchParams.sort_field
            const sortDirection = searchParams.sort_direction

            if (sortField && sortDirection && (sortDirection === 'ASC' || sortDirection === 'DESC')) {
                const orderBy = parseInt(sortField, 10)
                if (!isNaN(orderBy) && values.marketingAnalyticsOrderBy?.[0] !== orderBy) {
                    actions.setMarketingAnalyticsOrderBy(orderBy, sortDirection as 'ASC' | 'DESC')
                }
            } else if (!sortField && !sortDirection && values.marketingAnalyticsOrderBy) {
                actions.clearMarketingAnalyticsOrderBy()
            }
        },
    })),
])
