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
