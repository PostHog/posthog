import React from 'react'

import { dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter, midEllipsis, pluralize } from 'lib/utils'
import { getConstrainedWeekRange } from 'lib/utils/dateTimeUtils'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { BreakdownFilter, DateRange } from '~/queries/schema/schema-general'
import { ActionFilter, CompareLabelType, FilterType, IntervalType } from '~/types'

import { formatBreakdownLabel } from '../utils'

export interface SeriesDatum {
    id: number // determines order that series will be displayed in
    dataIndex: number
    datasetIndex: number
    breakdown_value?: string | number | string[]
    compare_label?: CompareLabelType
    action?: ActionFilter
    label?: string
    order: number
    dotted?: boolean
    color?: string
    count: number
    filter?: FilterType
    hideTooltip?: boolean
}

// Describes the row-by-row data for insight tooltips in the situation where series
// are itemized as columns instead of rows by default
export interface InvertedSeriesDatum {
    id: string
    datasetIndex: number
    color?: string
    datumTitle: React.ReactNode
    seriesData: SeriesDatum[]
}

export interface TooltipConfig {
    altTitle?: string | ((tooltipData: SeriesDatum[], formattedDate: string) => React.ReactNode)
    altRightTitle?: string | ((tooltipData: SeriesDatum[], formattedDate: string) => React.ReactNode)
    rowCutoff?: number
    colCutoff?: number
    renderSeries?: (value: React.ReactNode, seriesDatum: SeriesDatum, idx: number) => React.ReactNode
    renderCount?: (value: number) => React.ReactNode
    showHeader?: boolean
    hideColorCol?: boolean
    groupTypeLabel?: string
    filter?: (s: SeriesDatum) => boolean
}

export interface InsightTooltipProps extends Omit<TooltipConfig, 'renderSeries' | 'renderCount'> {
    renderSeries: Required<TooltipConfig>['renderSeries']
    renderCount: Required<TooltipConfig>['renderCount']
    /**
     * Whether the tooltip should be rendered as a table embeddable into an existing popover
     * (instead of as a popover of its own)
     * @default false
     */
    embedded?: boolean
    date?: string
    hideInspectActorsSection?: boolean
    seriesData: SeriesDatum[]
    breakdownFilter?: BreakdownFilter | undefined | null
    groupTypeLabel?: string
    timezone?: string | undefined
    interval?: IntervalType | null
    dateRange?: DateRange | null
}

export interface FormattedDateOptions {
    interval?: IntervalType | null
    dateRange?: DateRange | null
    timezone?: string
    weekStartDay?: number // 0 for Sunday, 1 for Monday, etc.
}

export const COL_CUTOFF = 4
export const ROW_CUTOFF = 8

export function getTooltipTitle(
    seriesData: SeriesDatum[],
    altTitleOrFn: string | ((tooltipData: SeriesDatum[], date: string) => React.ReactNode),
    formattedDate: string
): React.ReactNode | null {
    // Use tooltip alternate title (or generate one if it's a function). Else default to date.
    if (altTitleOrFn) {
        if (typeof altTitleOrFn === 'function') {
            return altTitleOrFn(seriesData, formattedDate)
        }
        return altTitleOrFn
    }
    return null
}

export const INTERVAL_UNIT_TO_DAYJS_FORMAT: Record<IntervalType, string> = {
    second: 'D MMM YYYY HH:mm:ss',
    minute: 'D MMM YYYY HH:mm:00',
    hour: 'D MMM YYYY HH:00',
    day: 'D MMM YYYY',
    week: 'D MMM YYYY',
    month: 'MMMM YYYY',
}

/**
 * Format a date range
 */
function formatDateRange(startDate: dayjs.Dayjs, endDate: dayjs.Dayjs): string {
    // Same year and month
    if (startDate.month() === endDate.month() && startDate.year() === endDate.year()) {
        return `${startDate.format('D')}-${endDate.format('D MMM YYYY')}`
    }

    // Same year but different months
    if (startDate.year() === endDate.year()) {
        return `${startDate.format('D MMM')} - ${endDate.format('D MMM YYYY')}`
    }

    // Different years
    return `${startDate.format('D MMM YYYY')} - ${endDate.format('D MMM YYYY')}`
}

export function getFormattedDate(input?: string | number, options?: FormattedDateOptions): string {
    const defaultOptions = {
        interval: 'day',
        timezone: 'UTC',
        weekStartDay: 0, // Default to Sunday
    }
    const { interval, dateRange, timezone, weekStartDay } = { ...defaultOptions, ...options }

    // Number of intervals (i.e. days, weeks)
    if (Number.isInteger(input)) {
        return pluralize(input as number, interval ?? 'day')
    }

    // Handle retention graph labels like "Day 0", "Week 12", etc.
    // retention tooltips don't show the date/header, so we don't need to format it
    if (typeof input === 'string' && /^(Day|Week|Month|Hour) \d+$/.test(input)) {
        return input
    }

    const day = dayjs.tz(input, timezone)
    if (input === undefined || !day.isValid()) {
        return String(input)
    }

    // Handle week interval separately
    if (interval === 'week') {
        const dateFrom = dayjs.tz(dateRange?.date_from, timezone)
        const dateTo = dayjs.tz(dateRange?.date_to, timezone)
        const { start: weekStart, end: weekEnd } = getConstrainedWeekRange(
            day,
            { start: dateFrom, end: dateTo },
            weekStartDay
        )
        return formatDateRange(weekStart, weekEnd)
    }

    // Handle all other intervals
    return day.format(INTERVAL_UNIT_TO_DAYJS_FORMAT[interval ?? 'day'])
}

function getPillValues(
    s: SeriesDatum,
    breakdownFilter: BreakdownFilter | null | undefined,
    cohorts: any,
    formatPropertyValueForDisplay: any
): string[] {
    const pillValues = []
    if (s.breakdown_value !== undefined) {
        pillValues.push(
            formatBreakdownLabel(s.breakdown_value, breakdownFilter, cohorts?.results, formatPropertyValueForDisplay)
        )
    }
    if (s.compare_label) {
        pillValues.push(capitalizeFirstLetter(String(s.compare_label)))
    }
    return pillValues
}

function getDatumTitle(s: SeriesDatum, breakdownFilter: BreakdownFilter | null | undefined): React.ReactNode {
    // NOTE: Assuming these logics are mounted elsewhere, and we're not interested in tracking changes.
    const cohorts = cohortsModel.findMounted()?.values?.allCohorts
    const formatPropertyValueForDisplay = propertyDefinitionsModel.findMounted()?.values?.formatPropertyValueForDisplay
    const pillValues = getPillValues(s, breakdownFilter, cohorts, formatPropertyValueForDisplay)
    if (pillValues.length > 0) {
        return (
            <>
                {pillValues.map((pill, index) => (
                    <React.Fragment key={pill}>
                        <span>{midEllipsis(pill, 60)}</span>
                        {index < pillValues.length - 1 && ' · '}
                    </React.Fragment>
                ))}
            </>
        )
    }

    // Technically should never reach this point because series data should have at least breakdown or compare values
    return 'Baseline'
}

export function invertDataSource(
    seriesData: SeriesDatum[],
    breakdownFilter: BreakdownFilter | null | undefined
): InvertedSeriesDatum[] {
    const flattenedData: Record<string, InvertedSeriesDatum> = {}

    seriesData.forEach((s) => {
        const datumKey = `${s.breakdown_value}-${s.compare_label}`
        if (datumKey in flattenedData) {
            flattenedData[datumKey].seriesData.push(s)
            flattenedData[datumKey].seriesData = flattenedData[datumKey].seriesData.sort((a, b) => a.order - b.order)
        } else {
            flattenedData[datumKey] = {
                id: datumKey,
                datasetIndex: s.datasetIndex,
                color: s.color,
                datumTitle: getDatumTitle(s, breakdownFilter),
                seriesData: [s],
            }
        }
    })

    return Object.values(flattenedData)
}
