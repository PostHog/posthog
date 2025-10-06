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
    MarketingAnalyticsColumnsSchemaNames,
    SourceMap,
} from '~/queries/schema/schema-general'
import { MARKETING_ANALYTICS_SCHEMA } from '~/queries/schema/schema-general'
import { DataWarehouseSettingsTab, ExternalDataSource, IntervalType } from '~/types'
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
                            sourceUrl: urls.dataWarehouseSource(
                                `${tableType}-${dataWarehouseSource?.id || table.source?.id || table.id}`
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
        createMarketingDataWarehouseNodes: [
            (s) => [s.validExternalTables, s.baseCurrency, s.validNativeSources, s.tileColumnSelection],
            (
                validExternalTables: ExternalTable[],
                baseCurrency: CurrencyCode,
                validNativeSources: NativeSource[],
                tileColumnSelection: validColumnsForTiles
            ): DataWarehouseNode[] => {
                const nonNativeNodeList: DataWarehouseNode[] = validExternalTables
                    .map((table) => externalAdsCostTile(table, baseCurrency, tileColumnSelection))
                    .filter(Boolean) as DataWarehouseNode[]

                const nativeNodeList: DataWarehouseNode[] = validNativeSources
                    .map((source) => MarketingDashboardMapper(source, tileColumnSelection))
                    .filter(Boolean) as DataWarehouseNode[]

                return [...nativeNodeList, ...nonNativeNodeList]
            },
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
