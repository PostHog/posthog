import { AnyResponseType } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { Column, ColumnScalar } from './types'

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

export const columnsFromResponseFields = (columns: string[] = [], types: string[][] = []): Column[] => {
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

export const columnsFromResponse = (response: AnyResponseType | null): Column[] => {
    if (!response) {
        return []
    }

    return columnsFromResponseFields(
        'columns' in response && Array.isArray(response.columns) ? response.columns : [],
        'types' in response && Array.isArray(response.types) ? response.types : []
    )
}

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

export const rowCountFromResponse = (response: AnyResponseType | null): number => {
    const rawResults =
        response && 'results' in response ? response.results : response && 'result' in response ? response.result : []
    return Array.isArray(rawResults) ? rawResults.length : 0
}

const hasTimeSeriesData = (columns: Column[], rowCount: number): boolean => {
    const hasDateColumn = columns.some((column) => ['DATE', 'DATETIME'].includes(column.type.name))
    const hasNumericColumn = columns.some((column) => column.type.isNumerical)

    return hasDateColumn && hasNumericColumn && rowCount > 1
}

export const getAutoVisualizationType = (columns: Column[], rowCount: number): ChartDisplayType => {
    if (hasTimeSeriesData(columns, rowCount)) {
        return ChartDisplayType.ActionsLineGraph
    }

    return resolveNonTimeSeriesVisualizationType(columns)
}
