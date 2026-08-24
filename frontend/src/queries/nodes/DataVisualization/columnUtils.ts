import { AnyResponseType } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { Column, ColumnScalar } from './types'

export const toFriendlyClickhouseTypeName = (type: string | undefined): ColumnScalar => {
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

export const isNumericalType = (type: ColumnScalar): boolean => {
    if (type === 'INTEGER' || type === 'FLOAT' || type === 'DECIMAL') {
        return true
    }

    return false
}

export const columnsFromResponse = (response: AnyResponseType | null): Column[] => {
    if (!response) {
        return []
    }

    const columns: string[] = 'columns' in response && Array.isArray(response.columns) ? response.columns : []
    const types: string[][] = 'types' in response && Array.isArray(response.types) ? response.types : []

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
}

// The axes a chart ends up with once the editor has finished setting it up. Same as the mount-time
// defaults, plus the promotion the editor applies when every column is numeric and so nothing is
// left to label the x axis.
export const deriveChartAxes = (columns: Column[]): { xAxis: string | null; yAxis: string[] } => {
    const defaults = deriveDefaultAxes(columns)
    if (defaults.xAxis || columns.length < 2 || !columns.every((column) => column.type.isNumerical)) {
        return defaults
    }

    const [first, ...rest] = columns
    return { xAxis: first.name, yAxis: rest.map((column) => column.name) }
}

// Which columns a chart plots when nothing has been picked yet: every numeric column on the y axis,
// and a date column on the x axis, falling back to the first column no y series claimed.
export const deriveDefaultAxes = (columns: Column[]): { xAxis: string | null; yAxis: string[] } => {
    const dateColumn = columns.find((column) => column.type.name.indexOf('DATE') !== -1)
    const numericalColumns = columns.filter((column) => column.type.isNumerical)
    const yAxis = numericalColumns.map((column) => column.name)

    if (dateColumn) {
        return { xAxis: dateColumn.name, yAxis }
    }

    const claimed = new Set(yAxis)
    return { xAxis: columns.find((column) => !claimed.has(column.name))?.name ?? null, yAxis }
}

const resolveNonTimeSeriesVisualizationType = (columns: Column[]): ChartDisplayType => {
    const stringColumns = columns.filter((column) => column.type.name === 'STRING')
    const numericalColumns = columns.filter((column) => column.type.isNumerical)

    if (stringColumns.length >= 2 && numericalColumns.length >= 1) {
        return ChartDisplayType.TwoDimensionalHeatmap
    }

    if (numericalColumns.length === 1 && columns.length === 1) {
        return ChartDisplayType.BoldNumber
    }

    if (numericalColumns.length > 0) {
        return ChartDisplayType.ActionsBar
    }

    return ChartDisplayType.ActionsTable
}

const hasTimeSeriesData = (columns: Column[], response: AnyResponseType | null): boolean => {
    const hasDateColumn = columns.some((column) => ['DATE', 'DATETIME'].includes(column.type.name))
    const hasNumericColumn = columns.some((column) => column.type.isNumerical)
    const rawResults =
        response && 'results' in response ? response.results : response && 'result' in response ? response.result : []
    // insightDataLogic always sets a `result` key, even when the response is empty, so the key being
    // present does not mean it holds an array.
    const results = Array.isArray(rawResults) ? rawResults : []

    return hasDateColumn && hasNumericColumn && results.length > 1
}

export const getAutoVisualizationType = (columns: Column[], response: AnyResponseType | null): ChartDisplayType => {
    if (hasTimeSeriesData(columns, response)) {
        return ChartDisplayType.ActionsLineGraph
    }

    return resolveNonTimeSeriesVisualizationType(columns)
}
