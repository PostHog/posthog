import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { dayjs } from 'lib/dayjs'
import { lightenDarkenColor, objectsEqual, RGBToHex, uuid } from 'lib/utils'
import mergeObject from 'lodash.merge'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import {
    AnyResponseType,
    ChartAxis,
    ChartSettings,
    ChartSettingsDisplay,
    ChartSettingsFormatting,
    ConditionalFormattingRule,
    DataVisualizationNode,
    HogQLVariable,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType, DashboardType, ItemMode } from '~/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { getQueryFeatures, QueryFeature } from '../DataTable/queryFeatures'
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
    insightMode: ItemMode
    dataNodeCollectionId: string
    setQuery?: (node: DataVisualizationNode) => void
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
            ['activeScene'],
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
    propsChanged(({ actions, props }, oldProps) => {
        if (props.query && !objectsEqual(props.query, oldProps.query)) {
            actions._setQuery(props.query)
        }
    }),
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
        setQuery: (node: DataVisualizationNode) => ({ node }),
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
        _setQuery: (node: DataVisualizationNode) => ({ node }),
    })),
    reducers(({ props }) => ({
        query: [
            props.query,
            {
                setQuery: (_, { node }) => node,
                _setQuery: (_, { node }) => node,
            },
        ],
        visualizationType: [
            props.query.display ?? ChartDisplayType.ActionsTable,
            {
                setVisualizationType: (_, { visualizationType }) => visualizationType,
            },
        ],
        tabularColumnSettings: [
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
        selectedXAxis: [
            null as string | null,
            {
                clearAxis: () => null,
                updateXSeries: (_, { columnName }) => columnName,
            },
        ],
        selectedYAxis: [
            null as (SelectedYAxis | null)[] | null,
            {
                clearAxis: () => null,
                addYSeries: (state, { columnName, settings, allNumericalColumns }) => {
                    if (!state && columnName !== undefined) {
                        return [{ name: columnName, settings: settings ?? DefaultAxisSettings() }]
                    }

                    if (!state) {
                        return [null]
                    }

                    if (!columnName) {
                        const ungraphedColumns = allNumericalColumns.filter(
                            (n) => !state.map((m) => m?.name).includes(n.name)
                        )
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
                deleteYSeries: (state, { seriesIndex }) => {
                    if (!state) {
                        return null
                    }

                    if (state.length <= 1) {
                        return [null]
                    }

                    const ySeries = [...state]

                    ySeries.splice(seriesIndex, 1)

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
        chartSettings: [
            props.query.chartSettings ?? ({} as ChartSettings),
            {
                updateChartSettings: (state, { settings }) => {
                    return { ...mergeObject(state, settings) }
                },
                setQuery: (state, { node }) => {
                    return { ...mergeObject(state, node.chartSettings ?? {}) }
                },
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
            (state, props) => [props.insightMode, state.dashboardId],
            (insightMode, dashboardId) => {
                if (dashboardId) {
                    return false
                }

                return insightMode == ItemMode.Edit
            },
        ],
        showResultControls: [
            (state, props) => [props.insightMode, state.dashboardId],
            (insightMode, dashboardId) => {
                if (insightMode === ItemMode.Edit) {
                    return true
                }

                return !dashboardId
            },
        ],
        presetChartHeight: [
            (state, props) => [props.key, state.dashboardId, state.activeScene],
            (key, dashboardId, activeScene) => {
                // Key for SQL editor based visiaulizations
                const sqlEditorScene = activeScene === Scene.SQLEditor

                if (activeScene === Scene.Insight) {
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
            (state) => [state.selectedYAxis, state.response, state.columns],
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
            (state) => [state.selectedXAxis, state.response, state.columns],
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
            (state) => [state.tabularColumns, state.response],
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
            (state) => [state.tabularColumnSettings, state.response, state.columns],
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
            (state) => [state.visualizationType],
            (visualizationType): boolean =>
                // BoldNumber relies on yAxis formatting so it's considered a table visualization
                visualizationType === ChartDisplayType.ActionsTable ||
                visualizationType === ChartDisplayType.BoldNumber,
        ],
        showTableSettings: [
            (state) => [state.visualizationType],
            (visualizationType): boolean =>
                visualizationType === ChartDisplayType.ActionsTable ||
                visualizationType === ChartDisplayType.BoldNumber,
        ],
    }),
    listeners(({ props, actions }) => ({
        updateChartSettings: ({ settings }) => {
            actions.setQuery({
                ...props.query,
                chartSettings: { ...(props.query.chartSettings ?? {}), ...settings },
            })
        },
        setQuery: ({ node }) => {
            if (props.setQuery) {
                props.setQuery(node)
            }
        },
        setVisualizationType: ({ visualizationType }) => {
            actions.setQuery({
                ...props.query,
                display: visualizationType,
            })
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.query.display) {
            actions.setVisualizationType(props.query.display)
        }

        if (props.query.chartSettings) {
            const { xAxis, yAxis } = props.query.chartSettings

            if (xAxis) {
                actions.updateXSeries(xAxis.column)
            }

            if (yAxis && yAxis.length) {
                yAxis.forEach((axis) => {
                    actions.addYSeries(axis.column, axis.settings)
                })
            }
        }

        if (props.query.tableSettings) {
            if (props.query.tableSettings.columns) {
                props.query.tableSettings.columns.forEach((column) => {
                    actions.addSeries(column.column, column.settings)
                })
            }
        }

        if (props.query.tableSettings?.conditionalFormatting?.length) {
            props.query.tableSettings.conditionalFormatting.forEach((rule) => {
                actions.addConditionalFormattingRule(rule)
            })
            actions.setConditionalFormattingRulesPanelActiveKeys([])
        }
    }),
    subscriptions(({ props, actions, values }) => ({
        columns: (value: Column[], oldValue: Column[]) => {
            // If response is cleared, then don't update any internal values
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
        selectedXAxis: (value: string | null) => {
            if (values.isTableVisualization) {
                return
            }

            const yColumns =
                values.selectedYAxis?.filter((n: SelectedYAxis | null): n is SelectedYAxis => Boolean(n)) ?? []
            const xColumn: ChartAxis | undefined = value !== null ? { column: value } : undefined

            actions.setQuery({
                ...props.query,
                chartSettings: {
                    ...(props.query.chartSettings ?? {}),
                    yAxis: yColumns.map((n) => ({ column: n.name, settings: n.settings })),
                    xAxis: xColumn,
                },
            })
        },
        selectedYAxis: (value: (SelectedYAxis | null)[] | null) => {
            if (values.isTableVisualization) {
                return
            }

            const yColumns = value?.filter((n: SelectedYAxis | null): n is SelectedYAxis => Boolean(n)) ?? []
            const xColumn: ChartAxis | undefined =
                values.selectedXAxis !== null ? { column: values.selectedXAxis } : undefined

            actions.setQuery({
                ...props.query,
                chartSettings: {
                    ...(props.query.chartSettings ?? {}),
                    yAxis: yColumns.map((n) => ({ column: n.name, settings: n.settings })),
                    xAxis: xColumn,
                },
            })
        },
        tabularColumnSettings: (value: (SelectedYAxis | null)[] | null) => {
            if (!values.isTableVisualization) {
                return
            }

            const columns = value?.filter((n: SelectedYAxis | null): n is SelectedYAxis => Boolean(n)) ?? []

            actions.setQuery({
                ...props.query,
                tableSettings: {
                    ...(props.query.tableSettings ?? {}),
                    columns: columns.map((n) => ({ column: n.name, settings: n.settings })),
                },
            })
        },
        conditionalFormattingRules: (rules: ConditionalFormattingRule[]) => {
            const saveableRules = rules.filter((n) => n.columnName && n.input && n.templateId && n.bytecode.length)

            actions.setQuery({
                ...props.query,
                tableSettings: {
                    ...(props.query.tableSettings ?? {}),
                    conditionalFormatting: saveableRules,
                },
            })
        },
    })),
])
