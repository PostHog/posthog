import { BIConfig, BIDateBucket } from '~/queries/schema/schema-business-intelligence'
import { escapeRawPropertyAsHogQLIdentifier } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import type { BIAnalysisInput } from './biAnalysis'
import { getBIDateField } from './biQueryFilters'

const BUCKET_START: Record<BIDateBucket, string> = {
    minute: 'toStartOfMinute',
    hour: 'toStartOfHour',
    day: 'toStartOfDay',
    week: 'toStartOfWeek',
    month: 'toStartOfMonth',
    quarter: 'toStartOfQuarter',
    year: 'toStartOfYear',
}

export function getBIMissingDatesDisabledReason(config: BIConfig): string | undefined {
    const dates = [...config.rows, ...config.columns].filter((field) => ['date', 'datetime'].includes(field.type))
    if (dates.length !== 1 || !dates[0].dateBucket) {
        return 'Add one date dimension with a time bucket first'
    }
    if (
        getBIDateField(config)?.expression !== dates[0].expression ||
        !config.dateRange?.date_from ||
        config.dateRange.date_from === 'all'
    ) {
        return 'Use the date dimension as the date column and select a bounded date range'
    }
    if (config.source?.connectionId) {
        return 'Date filling is available for project and warehouse tables'
    }
    if (
        ![
            ChartDisplayType.Auto,
            ChartDisplayType.ActionsTable,
            ChartDisplayType.ActionsLineGraph,
            ChartDisplayType.ActionsAreaGraph,
            ChartDisplayType.ActionsBar,
            ChartDisplayType.ActionsStackedBar,
        ].includes(config.chartType)
    ) {
        return 'Use a table or time-series chart to fill missing dates'
    }
}

export function buildBIFilledPeriod(
    config: BIConfig,
    input: BIAnalysisInput,
    previous: boolean,
    totals: boolean
): string | null {
    if (!config.missingDates || getBIMissingDatesDisabledReason(config)) {
        return null
    }
    const dimensions = [...input.rows, ...input.columns]
    const date = dimensions.find(({ field }) => ['date', 'datetime'].includes(field.type))!
    const bucket = date.field.dateBucket!
    const start = BUCKET_START[bucket]
    const period = `bi_${previous ? 'previous' : 'current'}`
    const measures = input.measures.map(({ alias }) => escapeRawPropertyAsHogQLIdentifier(alias))
    const select = [
        ...dimensions.map(({ alias }) => alias),
        ...measures.map((alias) => `toNullable(toFloat(${alias})) AS ${alias}`),
        ...(totals ? ['bi_grouping', ...dimensions.map((_, index) => `bi_grouping_${index}`)] : []),
    ].join(', ')
    const order = [
        ...dimensions.filter((dimension) => dimension !== date).map(({ alias }) => `${alias} ASC`),
        `${date.alias} ASC WITH FILL FROM ${start}({filters.dateRange.from}) TO ${start}({filters.dateRange.to}) + INTERVAL 1 ${bucket.toUpperCase()} STEP INTERVAL 1 ${bucket.toUpperCase()}`,
    ]
    const interpolate =
        config.missingDates === 'zero' ? ` INTERPOLATE (${measures.map((alias) => `${alias} AS 0`).join(', ')})` : ''
    return `${period}_filled AS ((SELECT ${select} FROM ${period}${totals ? ' WHERE bi_grouping = 0' : ''} ORDER BY ${order.join(', ')}${interpolate})${totals ? ` UNION ALL SELECT ${select} FROM ${period} WHERE bi_grouping != 0` : ''})`
}
