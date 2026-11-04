import { escapePropertyAsHogQLIdentifier } from '~/queries/utils'

import type { DataQualityOutputColumnApi } from './generated/api.schemas'

export type MetricStarterKey = 'has_rows' | 'value_in_range' | 'no_sharp_drop'

export const OWN_SQL_TEMPLATE_KEY = 'own_sql'

export interface MetricStarterCheck {
    key: MetricStarterKey
    title: string
    description: string
}

export const METRIC_STARTER_CHECKS: MetricStarterCheck[] = [
    {
        key: 'has_rows',
        title: 'Metric returns data',
        description: 'Fails when the metric comes back with no rows.',
    },
    {
        key: 'value_in_range',
        title: 'Value stays in a range',
        description: 'Fails when a value is below 0 or above 1,000,000. Change the limits to fit your metric.',
    },
    {
        key: 'no_sharp_drop',
        title: 'Value does not drop sharply',
        description: 'Fails when the value falls by more than half from one period to the next.',
    },
]

const VALUE_COLUMN_PLACEHOLDER = '<value column>'
const TIME_COLUMN_PLACEHOLDER = '<time column>'
const NUMERIC_TYPE = /^(Nullable\()?(U?Int|Float|Decimal)/
const TIME_TYPE = /^(Nullable\()?Date/

function firstColumnOfType(columns: DataQualityOutputColumnApi[], type: RegExp): string | null {
    const name = columns.find((column) => column.type && type.test(column.type))?.name
    return name ? escapePropertyAsHogQLIdentifier(name) : null
}

export function metricStarterQuery(key: MetricStarterKey, columns: DataQualityOutputColumnApi[]): string {
    const value = firstColumnOfType(columns, NUMERIC_TYPE) ?? VALUE_COLUMN_PLACEHOLDER
    const time = firstColumnOfType(columns, TIME_TYPE) ?? TIME_COLUMN_PLACEHOLDER
    switch (key) {
        case 'has_rows':
            return 'SELECT row_count\nFROM (SELECT count() AS row_count FROM {metric})\nWHERE row_count = 0'
        case 'value_in_range':
            return `SELECT *\nFROM {metric}\nWHERE ${value} < 0 OR ${value} > 1000000`
        case 'no_sharp_drop':
            return `SELECT *\nFROM (\n    SELECT\n        ${time},\n        ${value},\n        lagInFrame(${value}) OVER (ORDER BY ${time}) AS previous_value\n    FROM {metric}\n)\nWHERE previous_value > 0\n    AND ${value} < previous_value * 0.5`
    }
}
