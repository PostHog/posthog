import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import mergeObject from 'lodash.merge'

import { dayjs } from 'lib/dayjs'
import { RGBToHex, lightenDarkenColor, uuid } from 'lib/utils'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import {
    AnyResponseType,
    ChartSettings,
    ChartSettingsDisplay,
    ChartSettingsFormatting,
    ConditionalFormattingRule,
    DataVisualizationNode,
    HogQLVariable,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType, DashboardType } from '~/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { QueryFeature, getQueryFeatures } from '../DataTable/queryFeatures'
import type { dataVisualizationLogicType } from './dataVisualizationLogicType'
import { ColumnScalar, FORMATTING_TEMPLATES } from './types'

export enum SideBarTab {
    Series = 'series',
    Display = 'display',
    ConditionalFormatting = 'conditional_formatting',
}

export interface ColumnType {
    name: ColumnScalar
    isNumerical: boolean
}

export interface Column {
    name: string
    type: ColumnType
    label: string
    dataIndex: number
}

export interface TableDataCell<T extends string | number | boolean | Date | null> {
    value: T
    formattedValue: string | object | null
    type: ColumnScalar
}

export interface AxisSeriesSettings {
    formatting?: ChartSettingsFormatting
    display?: ChartSettingsDisplay
}

export interface AxisSeries<T> {
    column: Column
    data: T[]
    settings?: AxisSeriesSettings
}

export interface DataVisualizationLogicProps {
    key: string
    query: DataVisualizationNode
    editMode?: boolean
    dataNodeCollectionId: string
    setQuery?: (setter: (node: DataVisualizationNode) => DataVisualizationNode) => void
    context?: QueryContext<DataVisualizationNode>
    cachedResults?: AnyResponseType
    insightLoading?: boolean
    dashboardId?: DashboardType['id']
    loadPriority?: number
    /** Dashboard variables to override the ones in the query */
    variablesOverride?: Record<string, HogQLVariable> | null
}

export interface SelectedYAxis {
    name: string
    settings: AxisSeriesSettings
}

export const EmptyYAxisSeries: AxisSeries<number> = {
    column: {
        name: 'None',
        type: {
            name: 'INTEGER',
            isNumerical: false,
        },
        label: 'None',
        dataIndex: -1,
    },
    data: [],
}

const DefaultAxisSettings = (): AxisSeriesSettings => ({
    formatting: {
        prefix: '',
        suffix: '',
    },
})

export const formatDataWithSettings = (
    data: number | string | null | object,
    settings?: AxisSeriesSettings
): string | object | null => {
    if (data === null || Number.isNaN(data)) {
        return null
    }

    if (typeof data === 'object') {
        return data
    }

    const decimalPlaces = settings?.formatting?.decimalPlaces

    let dataAsString = `${data}`

    if (typeof data === 'number') {
        dataAsString = `${decimalPlaces ? data.toFixed(decimalPlaces) : data}`

        if (settings?.formatting?.style === 'number') {
            dataAsString = data.toLocaleString(undefined, { maximumFractionDigits: decimalPlaces })
        }

        if (settings?.formatting?.style === 'percent') {
            dataAsString = `${data.toLocaleString(undefined, { maximumFractionDigits: decimalPlaces })}%`
        }
    }

    if (settings?.formatting?.prefix) {
        dataAsString = `${settings.formatting.prefix}${dataAsString}`
    }

    if (settings?.formatting?.suffix) {
        dataAsString = `${dataAsString}${settings.formatting.suffix}`
    }

    return dataAsString
}

export const convertTableValue = (
    value: string | number | null,
    type: ColumnScalar
): string | number | boolean | null => {
    if (value == null) {
        return null
    }

    if (type === 'STRING') {
        return value.toString()
    }

    if (type === 'INTEGER') {
        if (typeof value === 'number') {
            return value
        }

        return parseInt(value)
    }

    if (type === 'FLOAT' || type === 'DECIMAL') {
        if (typeof value === 'number') {
            return value
        }

        return parseFloat(value)
    }

    if (type === 'BOOLEAN') {
        return Boolean(value)
    }

    if (type === 'DATE' || type === 'DATETIME') {
        return dayjs(value).unix()
    }

    return value
}

const toFriendlyClickhouseTypeName = (type: string | undefined): ColumnScalar => {
    if (!type) {
        return 'UNKNOWN'
    }

    if (type.indexOf('Array') !== -1) {
        return 'ARRAY'
    }
    if (type.indexOf('Tuple') !== -1) {
        return 'TUPLE'
    }
    if (type.indexOf('Int') !== -1) {
        return 'INTEGER'
    }
    if (type.indexOf('Float') !== -1) {
        return 'FLOAT'
    }
    if (type.indexOf('DateTime') !== -1) {
        return 'DATETIME'
    }
    if (type.indexOf('Date') !== -1) {
        return 'DATE'
    }
    if (type.indexOf('Boolean') !== -1) {
        return 'BOOLEAN'
    }
    if (type.indexOf('Decimal') !== -1) {
        return 'DECIMAL'
    }
    if (type.indexOf('String') !== -1) {
        return 'STRING'
    }

    return type as ColumnScalar
}

const isNumericalType = (type: ColumnScalar): boolean => {
    if (type === 'INTEGER' || type === 'FLOAT' || type === 'DECIMAL') {
        return true
    }

    return false
}

export const dataVisualizationLogic = kea<dataVisualizationLogicType>([
    key((props) => props.key),
    path(['queries', 'nodes', 'DataVisualization', 'dataVisualizationLogic']),
    connect((props: DataVisualizationLogicProps) => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            dataNodeLogic({
                cachedResults: props.cachedResults,
                key: props.key,
                query: props.query.source,
                dataNodeCollectionId: props.dataNodeCollectionId,
                loadPriority: props.loadPriority,
                variablesOverride: props.variablesOverride,
            }),
            ['response', 'responseLoading', 'responseError', 'queryCancelled'],
            themeLogic,
            ['isDarkModeOn'],
            sceneLogic,
            ['activeSceneId'],
        ],
        actions: [
            dataNodeLogic({
                cachedResults: props.cachedResults,
                key: props.key,
                query: props.query.source,
                dataNodeCollectionId: props.dataNodeCollectionId,
                loadPriority: props.loadPriority,
                variablesOverride: props.variablesOverride,
            }),
            ['loadData'],
        ],
    })),
    props({ query: { source: {} } } as DataVisualizationLogicProps),
    actions(({ values }) => ({
        setVisualizationType: (visualizationType: ChartDisplayType) => ({ visualizationType }),
        updateXSeries: (columnName: string) => ({
            columnName,
        }),
        updateSeriesIndex: (seriesIndex: number, columnName: string, settings?: AxisSeriesSettings) => ({
            seriesIndex,
            columnName,
            settings,
        }),
        updateSeries: (columnName: string, settings?: AxisSeriesSettings) => ({ columnName, settings }),
        addYSeries: (columnName?: string, settings?: AxisSeriesSettings) => ({
            columnName,
            settings,
            allNumericalColumns: values.numericalColumns,
        }),
        addSeries: (columnName?: string, settings?: AxisSeriesSettings) => ({
            columnName,
            settings,
            allColumns: values.columns,
        }),
        deleteYSeries: (seriesIndex: number) => ({ seriesIndex }),
        clearAxis: true,
        setQuery: (setter: (node: DataVisualizationNode) => DataVisualizationNode) => ({ setter }),
        updateChartSettings: (settings: ChartSettings) => ({ settings }),
        setSideBarTab: (tab: SideBarTab) => ({ tab }),
        toggleChartSettingsPanel: (open?: boolean) => ({ open }),
        addConditionalFormattingRule: (rule?: ConditionalFormattingRule) => ({
            rule: rule ?? { id: uuid() },
            isDarkModeOn: values.isDarkModeOn,
        }),
        updateConditionalFormattingRule: (rule: ConditionalFormattingRule, deleteRule?: boolean) => ({
            rule,
            deleteRule,
            colorMode: values.isDarkModeOn ? 'dark' : 'light',
        }),
        setConditionalFormattingRulesPanelActiveKeys: (keys: string[]) => ({ keys }),
        // _setQuery: (node: DataVisualizationNode) => ({ node }),
    })),
    reducers(() => ({
        __tabularColumnSettings: [
            null as (SelectedYAxis | null)[] | null,
            {
                clearAxis: () => null,
                addSeries: (state, { columnName, settings, allColumns }) => {
                    if (!state && columnName !== undefined) {
                        return [{ name: columnName, settings: settings ?? DefaultAxisSettings() }]
                    }

                    if (!state) {
                        return [null]
                    }

                    if (!columnName) {
                        const ungraphedColumns = allColumns.filter((n) => !state.map((m) => m?.name).includes(n.name))
                        if (ungraphedColumns.length > 0) {
                            return [
                                ...state,
                                { name: ungraphedColumns[0].name, settings: settings ?? DefaultAxisSettings() },
                            ]
                        }
                    }

                    return [
                        ...state,
                        columnName === undefined
                            ? null
                            : { name: columnName, settings: settings ?? DefaultAxisSettings() },
                    ]
                },
                updateSeries: (state, { columnName, settings }) => {
                    if (!state) {
                        return null
                    }

                    const ySeries = [...state]

                    const index = ySeries.findIndex((n) => n?.name === columnName)
                    if (index < 0) {
                        return ySeries
                    }

                    ySeries[index] = {
                        name: columnName,
                        settings: mergeObject(ySeries[index]?.settings ?? {}, settings),
                    }
                    return ySeries
                },
                updateSeriesIndex: (state, { seriesIndex, columnName, settings }) => {
                    if (!state) {
                        return null
                    }

                    const ySeries = [...state]

                    ySeries[seriesIndex] = {
                        name: columnName,
                        settings: mergeObject(ySeries[seriesIndex]?.settings ?? {}, settings),
                    }
                    return ySeries
                },
            },
        ],
        activeSideBarTab: [
            SideBarTab.Series as SideBarTab,
            {
                setSideBarTab: (_state, { tab }) => tab,
            },
        ],
        isChartSettingsPanelOpen: [
            false as boolean,
            {
                toggleChartSettingsPanel: (state, { open }) => {
                    if (open === undefined) {
                        return !state
                    }

                    return open
                },
                setVisualizationType: (state, { visualizationType }) => {
                    if (state) {
                        return true
                    }

                    return visualizationType !== ChartDisplayType.ActionsTable
                },
            },
        ],
        conditionalFormattingRules: [
            [] as ConditionalFormattingRule[],
            {
                _setQuery: (state, { node }) => {
                    if (node.tableSettings?.conditionalFormatting) {
                        return node.tableSettings.conditionalFormatting
                    }
                    return state
                },
                addConditionalFormattingRule: (state, { rule, isDarkModeOn }) => {
                    const rules = [...state]

                    rules.push({
                        templateId: FORMATTING_TEMPLATES[0].id,
                        columnName: '',
                        bytecode: [],
                        input: '',
                        color: isDarkModeOn ? RGBToHex(lightenDarkenColor('#FFADAD', -30)) : '#FFADAD',
                        ...rule,
                    })

                    return rules
                },
                updateConditionalFormattingRule: (state, { rule, deleteRule, colorMode }) => {
                    const rules = [...state]

                    const index = rules.findIndex((n) => n.id === rule.id)
                    if (index === -1) {
                        return rules
                    }

                    if (deleteRule) {
                        rules.splice(index, 1)
                        return rules
                    }

                    rules[index] = { ...rule, colorMode: colorMode as 'light' | 'dark' }
                    return rules
                },
            },
        ],
        conditionalFormattingRulesPanelActiveKeys: [
            [] as string[],
            {
                _setQuery: (state, { node }) => {
                    if (node.tableSettings?.conditionalFormatting) {
                        return node.tableSettings.conditionalFormatting.map((n) => n.id)
                    }
                    return state
                },
                addConditionalFormattingRule: (state, { rule: { id } }) => {
                    return [...state, id]
                },
                setConditionalFormattingRulesPanelActiveKeys: (_, { keys }) => {
                    return [...keys]
                },
            },
        ],
    })),
    selectors({
        query: [() => [(_, p) => p.query], (query: DataVisualizationNode): DataVisualizationNode => query],
        visualizationType: [
            (s) => [s.query],
            (query: DataVisualizationNode) => query.display ?? ChartDisplayType.ActionsTable,
        ],
        selectedXAxis: [(s) => [s.query], (query: DataVisualizationNode) => query.chartSettings?.xAxis?.column ?? null],
        selectedYAxis: [
            (s) => [s.query],
            (query: DataVisualizationNode) =>
                query.chartSettings?.yAxis?.map((axis) => ({
                    name: axis.column,
                    settings: axis.settings ?? DefaultAxisSettings(),
                })) ?? null,
        ],
        chartSettings: [(s) => [s.query], (query: DataVisualizationNode) => query.chartSettings ?? {}],
        tabularColumnSettings: [
            (s) => [s.query],
            (query: DataVisualizationNode): (SelectedYAxis | null)[] | null => {
                if (query.tableSettings?.columns) {
                    return query.tableSettings.columns.map((column) => ({
                        name: column.column,
                        settings: column.settings ?? DefaultAxisSettings(),
                    }))
                }
                return null
            },
        ],
        columns: [
            (s) => [s.response],
            (response): Column[] => {
                if (!response) {
                    return []
                }

                const columns: string[] = response['columns'] ?? []
                const types: string[][] = response['types'] ?? []

                return columns.map((column, index) => {
                    const type = types[index]?.[1]
                    const friendlyClickhouseTypeName = toFriendlyClickhouseTypeName(type)

                    return {
                        name: column,
                        type: {
                            name: friendlyClickhouseTypeName,
                            isNumerical: isNumericalType(friendlyClickhouseTypeName),
                        },
                        label: `${column} - ${type}`,
                        dataIndex: index,
                    }
                })
            },
        ],
        numericalColumns: [
            (s) => [s.columns],
            (columns): Column[] => {
                return columns.filter((n) => n.type.isNumerical)
            },
        ],
        dashboardId: [() => [(_, props) => props.dashboardId], (dashboardId) => dashboardId ?? null],
        showEditingUI: [
            (s) => [(_, props: DataVisualizationLogicProps) => props.editMode, s.dashboardId],
            (editMode, dashboardId) => {
                if (dashboardId) {
                    return false
                }
                return !!editMode
            },
        ],
        showResultControls: [
            (s) => [(_, props: DataVisualizationLogicProps) => props.editMode, s.dashboardId],
            (editMode, dashboardId) => {
                if (editMode) {
                    return true
                }

                return !dashboardId
            },
        ],
        presetChartHeight: [
            (s, props) => [props.key, s.dashboardId, s.activeSceneId],
            (key, dashboardId, activeSceneId) => {
                // Key for SQL editor based visiaulizations
                const sqlEditorScene = activeSceneId === Scene.SQLEditor

                if (activeSceneId === Scene.Insight) {
                    return true
                }

                return !key.includes('new-SQL') && !dashboardId && !sqlEditorScene
            },
        ],
        sourceFeatures: [(_, props) => [props.query], (query): Set<QueryFeature> => getQueryFeatures(query.source)],
        isShowingCachedResults: [
            () => [(_, props) => props.cachedResults ?? null],
            (cachedResults: AnyResponseType | null): boolean => !!cachedResults,
        ],
        yData: [
            (s) => [s.selectedYAxis, s.response, s.columns],
            (ySeries, response, columns): AxisSeries<number>[] => {
                if (!response || ySeries === null || ySeries.length === 0) {
                    return [EmptyYAxisSeries]
                }

                const data: any[] = response?.['results'] ?? response?.['result'] ?? []

                return ySeries
                    .map((series): AxisSeries<number> | null => {
                        if (!series) {
                            return EmptyYAxisSeries
                        }

                        const column = columns.find((n) => n.name === series.name)
                        if (!column) {
                            return EmptyYAxisSeries
                        }

                        return {
                            column,
                            data: data.map((n) => {
                                try {
                                    const multiplier = series.settings.formatting?.style === 'percent' ? 100 : 1

                                    if (series.settings.formatting?.decimalPlaces) {
                                        return parseFloat(
                                            (parseFloat(n[column.dataIndex]) * multiplier).toFixed(
                                                series.settings.formatting.decimalPlaces
                                            )
                                        )
                                    }

                                    const isNotANumber =
                                        Number.isNaN(n[column.dataIndex]) ||
                                        n[column.dataIndex] === undefined ||
                                        n[column.dataIndex] === null
                                    if (isNotANumber) {
                                        return 0
                                    }

                                    const isInt = Number.isInteger(n[column.dataIndex])
                                    return isInt
                                        ? parseInt(n[column.dataIndex], 10) * multiplier
                                        : parseFloat(n[column.dataIndex]) * multiplier
                                } catch {
                                    return 0
                                }
                            }),
                            settings: series.settings,
                        }
                    })
                    .filter((series): series is AxisSeries<number> => Boolean(series))
            },
        ],
        xData: [
            (s) => [s.selectedXAxis, s.response, s.columns],
            (xSeries, response, columns): AxisSeries<string> | null => {
                if (!response || xSeries === null) {
                    return {
                        column: {
                            name: 'None',
                            type: {
                                name: 'STRING',
                                isNumerical: false,
                            },
                            label: 'None',
                            dataIndex: -1,
                        },
                        data: [],
                    }
                }

                const data: any[] = response?.['results'] ?? response?.['result'] ?? []

                const column = columns.find((n) => n.name === xSeries)
                if (!column) {
                    return null
                }

                return {
                    column,
                    data: data.map((n) => n[column.dataIndex]),
                }
            },
        ],
        tabularData: [
            (s) => [s.tabularColumns, s.response],
            (tabularColumns, response): TableDataCell<any>[][] => {
                if (!response || tabularColumns === null) {
                    return []
                }

                const data: (string | number | null)[][] = response?.['results'] ?? response?.['result'] ?? []

                return data.map((row): TableDataCell<any>[] => {
                    return tabularColumns.map((column): TableDataCell<any> => {
                        if (!column) {
                            return {
                                value: null,
                                formattedValue: null,
                                type: 'STRING',
                            }
                        }

                        const value = row[column.column.dataIndex]

                        if (column.column.type.isNumerical) {
                            try {
                                if (value === null) {
                                    return {
                                        value: null,
                                        formattedValue: null,
                                        type: column.column.type.name,
                                    }
                                }

                                const multiplier = column.settings?.formatting?.style === 'percent' ? 100 : 1

                                if (column.settings?.formatting?.decimalPlaces) {
                                    return {
                                        value,
                                        formattedValue: formatDataWithSettings(
                                            parseFloat(
                                                (parseFloat(value.toString()) * multiplier).toFixed(
                                                    column.settings.formatting.decimalPlaces
                                                )
                                            ),
                                            column.settings
                                        ),
                                        type: column.column.type.name,
                                    }
                                }

                                const isInt = Number.isInteger(value)
                                return {
                                    value,
                                    formattedValue: formatDataWithSettings(
                                        isInt
                                            ? parseInt(value.toString(), 10) * multiplier
                                            : parseFloat(value.toString()) * multiplier,
                                        column.settings
                                    ),
                                    type: column.column.type.name,
                                }
                            } catch {
                                return {
                                    value: 0,
                                    formattedValue: '0',
                                    type: column.column.type.name,
                                }
                            }
                        }

                        return {
                            value: convertTableValue(value, column.column.type.name),
                            formattedValue: formatDataWithSettings(value, column.settings),
                            type: column.column.type.name,
                        }
                    })
                })
            },
        ],
        tabularColumns: [
            (s) => [s.tabularColumnSettings, s.response, s.columns],
            (tabularColumnSettings, response, columns): AxisSeries<any>[] => {
                if (!response) {
                    return []
                }

                return columns.map((col) => {
                    const series = (tabularColumnSettings || []).find((n) => n?.name === col.name)

                    return {
                        column: col,
                        data: [],
                        settings: series?.settings ?? DefaultAxisSettings(),
                    }
                })
            },
        ],
        dataVisualizationProps: [() => [(_, props) => props], (props): DataVisualizationLogicProps => props],
        isTableVisualization: [
            (s) => [s.visualizationType],
            (visualizationType): boolean =>
                // BoldNumber relies on yAxis formatting so it's considered a table visualization
                visualizationType === ChartDisplayType.ActionsTable ||
                visualizationType === ChartDisplayType.BoldNumber,
        ],
        showTableSettings: [
            (s) => [s.visualizationType],
            (visualizationType): boolean =>
                visualizationType === ChartDisplayType.ActionsTable ||
                visualizationType === ChartDisplayType.BoldNumber,
        ],
    }),
    listeners(({ props, actions }) => ({
        setQuery: ({ setter }) => {
            if (props.setQuery) {
                props.setQuery(setter)
            }
        },
        setVisualizationType: ({ visualizationType }) => {
            actions.setQuery((query) => ({
                ...query,
                display: visualizationType,
            }))
        },
        updateChartSettings: ({ settings }) => {
            actions.setQuery((query) => ({
                ...query,
                chartSettings: { ...query.chartSettings, ...settings },
            }))
        },
        clearAxis: () => {
            actions.setQuery((query) => ({
                ...query,
                chartSettings: {
                    ...query.chartSettings,
                    xAxis: undefined,
                    yAxis: [],
                },
                tableSettings: {
                    ...query.tableSettings,
                    columns: [],
                },
            }))
        },
        updateXSeries: ({ columnName }) => {
            actions.setQuery((query) => ({
                ...query,
                chartSettings: {
                    ...query.chartSettings,
                    xAxis: { column: columnName },
                },
            }))
        },
        addYSeries: ({ columnName, settings, allNumericalColumns }) => {
            actions.setQuery((query) => {
                const currentYSeries = query.chartSettings?.yAxis ?? []

                let newYSeries: { column: string; settings?: AxisSeriesSettings }[]

                if (!currentYSeries.length && columnName !== undefined) {
                    newYSeries = [{ column: columnName, settings: settings ?? DefaultAxisSettings() }]
                } else if (!currentYSeries.length) {
                    const firstColumn = allNumericalColumns[0]
                    if (firstColumn) {
                        newYSeries = [{ column: firstColumn.name, settings: settings ?? DefaultAxisSettings() }]
                    } else {
                        newYSeries = [{ column: 'None', settings: settings ?? DefaultAxisSettings() }]
                    }
                } else if (!columnName) {
                    const ungraphedColumns = allNumericalColumns.filter(
                        (n) => !currentYSeries.map((m) => m.column).includes(n.name)
                    )
                    if (ungraphedColumns.length > 0) {
                        newYSeries = [
                            ...currentYSeries,
                            { column: ungraphedColumns[0].name, settings: settings ?? DefaultAxisSettings() },
                        ]
                    } else {
                        newYSeries = [...currentYSeries]
                    }
                } else {
                    newYSeries = [
                        ...currentYSeries,
                        { column: columnName, settings: settings ?? DefaultAxisSettings() },
                    ]
                }

                // Ensure no duplicate columns
                newYSeries = newYSeries.filter(
                    (series, index, self) => index === self.findIndex((s) => s.column === series.column)
                )

                return {
                    ...query,
                    chartSettings: {
                        ...query.chartSettings,
                        yAxis: newYSeries,
                    },
                }
            })
        },
        updateSeriesIndex: ({ seriesIndex, columnName, settings }) => {
            actions.setQuery((query) => {
                const currentYSeries = query.chartSettings?.yAxis ?? []

                if (seriesIndex < 0 || seriesIndex >= currentYSeries.length) {
                    return query
                }

                const newYSeries = [...currentYSeries]

                newYSeries[seriesIndex] = {
                    column: columnName,
                    settings: mergeObject(newYSeries[seriesIndex]?.settings ?? {}, settings),
                }

                return {
                    ...query,
                    chartSettings: {
                        ...query.chartSettings,
                        yAxis: newYSeries,
                    },
                }
            })
        },
        updateSeries: ({ columnName, settings }) => {
            actions.setQuery((query) => {
                const currentYSeries = query.chartSettings?.yAxis ?? []

                const index = currentYSeries.findIndex((n) => n.column === columnName)
                if (index < 0) {
                    return query
                }

                const newYSeries = [...currentYSeries]

                newYSeries[index] = {
                    column: columnName,
                    settings: mergeObject(newYSeries[index]?.settings ?? {}, settings),
                }

                return {
                    ...query,
                    chartSettings: {
                        ...query.chartSettings,
                        yAxis: newYSeries,
                    },
                }
            })
        },
        deleteYSeries: ({ seriesIndex }) => {
            actions.setQuery((query) => {
                const currentYSeries = query.chartSettings?.yAxis ?? []

                if (seriesIndex < 0 || seriesIndex >= currentYSeries.length) {
                    return query
                }

                if (currentYSeries.length <= 1) {
                    return {
                        ...query,
                        chartSettings: {
                            ...query.chartSettings,
                            yAxis: [],
                        },
                    }
                }

                const newYSeries = [...currentYSeries]
                newYSeries.splice(seriesIndex, 1)

                return {
                    ...query,
                    chartSettings: {
                        ...query.chartSettings,
                        yAxis: newYSeries,
                    },
                }
            })
        },
    })),
    subscriptions(({ actions, values }) => ({
        columns: (value: Column[], oldValue: Column[]) => {
            // If the response is cleared, then don't update any internal values
            if (!values.response || (!(values.response as any).results && !(values.response as any).result)) {
                return
            }

            // When query columns update, clear all internal values and re-setup tabular columns and chart series

            const oldTabularColumnSettings: (SelectedYAxis | null)[] | null = JSON.parse(
                JSON.stringify(values.tabularColumnSettings)
            )

            if (oldValue && oldValue.length) {
                if (JSON.stringify(value) !== JSON.stringify(oldValue)) {
                    actions.clearAxis()
                }
            }

            // Set up table columns
            if (values.response && values.tabularColumnSettings === null) {
                value.forEach((column) => {
                    if (oldTabularColumnSettings) {
                        const lastValue = oldTabularColumnSettings.find((n) => n?.name === column.name)
                        return actions.addSeries(column.name, lastValue?.settings)
                    }

                    actions.addSeries(column.name)
                })
            }

            // Set up chart series
            if (values.response && values.selectedXAxis === null && values.selectedYAxis === null) {
                const xAxisTypes = value.find((n) => n.type.name.indexOf('DATE') !== -1)
                const yAxisTypes = value.filter((n) => n.type.isNumerical)

                if (yAxisTypes) {
                    yAxisTypes.forEach((y) => {
                        if (oldTabularColumnSettings) {
                            const lastValue = oldTabularColumnSettings.find((n) => n?.name === y.name)
                            return actions.addYSeries(y.name, lastValue?.settings)
                        }

                        actions.addYSeries(y.name)
                    })
                }

                if (xAxisTypes) {
                    actions.updateXSeries(xAxisTypes.name)
                }
            }
        },
        conditionalFormattingRules: (rules: ConditionalFormattingRule[]) => {
            const saveableRules = rules.filter((n) => n.columnName && n.input && n.templateId && n.bytecode.length)

            actions.setQuery((query) => ({
                ...query,
                tableSettings: {
                    ...query.tableSettings,
                    conditionalFormatting: saveableRules,
                },
            }))
        },
    })),
])
