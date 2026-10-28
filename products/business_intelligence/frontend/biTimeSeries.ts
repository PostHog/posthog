import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'

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
        const from = dateStringToDayJs(config.dateRange.date_from)
        const to = config.dateRange.date_to ? dateStringToDayJs(config.dateRange.date_to) : dayjs()
        if (!from?.isValid() || !to?.isValid() || to.diff(from, dates[0].dateBucket) >= 49999) {
            return 'Use fewer than 50,000 date buckets: shorten the range or choose a wider time bucket'
        }
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
    const dateRange = config.comparisonPeriod ? 'filters.previous.dateRange' : 'filters.dateRange'
    const period = `bi_${previous ? 'previous' : 'current'}`
    const measures = input.measures.map(({ alias }) => escapeRawPropertyAsHogQLIdentifier(alias))
    if (config.source?.connectionId) {
        const add: Record<BIDateBucket, string> = {
            minute: 'addMinutes',
            hour: 'addHours',
            day: 'addDays',
            week: 'addWeeks',
            month: 'addMonths',
            quarter: 'addQuarters',
            year: 'addYears',
        }
        // A bounded decimal spine also runs on engines without generate_series (such as Redshift).
        const digits = Array.from({ length: 10 }, (_, index) => `SELECT ${index} AS n`).join(' UNION ALL ')
        const sequence = 'd0.n + 10 * d1.n + 100 * d2.n + 1000 * d3.n + 10000 * d4.n'
        const others = dimensions.filter((dimension) => dimension !== date)
        const groups = others.map(({ alias }) => alias)
        const detail = totals ? ' WHERE bi_grouping = 0' : ''
        const spine = `${add[bucket]}(${start}({${dateRange}.from}), ${sequence})`
        const projection = dimensions.map(
            ({ alias }) => `${alias === date.alias ? 'bi_dates' : 'bi_series'}.${alias} AS ${alias}`
        )
        const match = dimensions
            .map(({ alias }) => {
                const key = `${alias === date.alias ? 'bi_dates' : 'bi_series'}.${alias}`
                return `(bi_observed.${alias} = ${key} OR (bi_observed.${alias} IS NULL AND ${key} IS NULL))`
            })
            .join(' AND ')
        const filled = measures.map(
            (alias) =>
                `if(bi_observed.bi_present = 1, toFloat(bi_observed.${alias}), ${config.missingDates === 'zero' ? '0' : 'NULL'}) AS ${alias}`
        )
        const flags = totals ? ['0 AS bi_grouping', ...dimensions.map((_, index) => `0 AS bi_grouping_${index}`)] : []
        const totalsSelect = [
            ...dimensions.map(({ alias }) => alias),
            ...measures,
            'bi_grouping',
            ...dimensions.map((_, index) => `bi_grouping_${index}`),
        ]
        return `${period}_filled AS (WITH bi_digits AS (${digits}), bi_dates AS (SELECT ${spine} AS ${date.alias} FROM bi_digits AS d0 CROSS JOIN bi_digits AS d1 CROSS JOIN bi_digits AS d2 CROSS JOIN bi_digits AS d3 CROSS JOIN bi_digits AS d4 WHERE d4.n < 5 AND ${spine} < {${dateRange}.to}), bi_series AS (SELECT DISTINCT ${groups.length ? groups.join(', ') : '1 AS bi_series_key'} FROM ${period}${detail}), bi_observed AS (SELECT *, 1 AS bi_present FROM ${period}${detail}) SELECT ${[...projection, ...filled, ...flags].join(', ')} FROM bi_dates CROSS JOIN bi_series LEFT JOIN bi_observed ON ${match}${totals ? ` UNION ALL SELECT ${totalsSelect.join(', ')} FROM ${period} WHERE bi_grouping != 0` : ''})`
    }
    const select = [
        ...dimensions.map(({ alias }) => alias),
        ...measures.map((alias) => `toNullable(toFloat(${alias})) AS ${alias}`),
        ...(totals ? ['bi_grouping', ...dimensions.map((_, index) => `bi_grouping_${index}`)] : []),
    ].join(', ')
    const order = [
        ...dimensions.filter((dimension) => dimension !== date).map(({ alias }) => `${alias} ASC`),
        `${date.alias} ASC WITH FILL FROM ${start}({${dateRange}.from}) TO {${dateRange}.to} STEP INTERVAL 1 ${bucket.toUpperCase()}`,
    ]
    const interpolate =
        config.missingDates === 'zero' ? ` INTERPOLATE (${measures.map((alias) => `${alias} AS 0`).join(', ')})` : ''
    return `${period}_filled AS ((SELECT ${select} FROM ${period}${totals ? ' WHERE bi_grouping = 0' : ''} ORDER BY ${order.join(', ')}${interpolate})${totals ? ` UNION ALL SELECT ${select} FROM ${period} WHERE bi_grouping != 0` : ''})`
}
