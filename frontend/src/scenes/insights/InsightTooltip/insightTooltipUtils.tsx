import { dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter, midEllipsis, pluralize } from 'lib/utils'
import React from 'react'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { BreakdownFilter } from '~/queries/schema/schema-general'
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
    timezone?: string | null
}

export const COL_CUTOFF = 4
export const ROW_CUTOFF = 8

export function getTooltipTitle(
    seriesData: SeriesDatum[],
    altTitleOrFn?: string | ((tooltipData: SeriesDatum[], date: string) => React.ReactNode),
    date?: string
): React.ReactNode | null {
    // Use tooltip alternate title (or generate one if it's a function). Else default to date.
    if (altTitleOrFn) {
        if (typeof altTitleOrFn === 'function') {
            return altTitleOrFn(seriesData, getFormattedDate(date))
        }
        return altTitleOrFn
    }
    return null
}

export const INTERVAL_UNIT_TO_DAYJS_FORMAT: Record<IntervalType, string> = {
    minute: 'DD MMM YYYY HH:mm:00',
    hour: 'DD MMM YYYY HH:00',
    day: 'DD MMM YYYY',
    week: 'DD MMM YYYY',
    month: 'MMMM YYYY',
}

export function getFormattedDate(input?: string | number, interval: IntervalType = 'day'): string {
    // Number of intervals (i.e. days, weeks)
    if (Number.isInteger(input)) {
        return pluralize(input as number, interval)
    }
    const day = dayjs(input)
    // Dayjs formatted day
    if (input !== undefined && day.isValid()) {
        return day.format(INTERVAL_UNIT_TO_DAYJS_FORMAT[interval])
    }
    return String(input)
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
