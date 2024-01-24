import { dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter, midEllipsis, pluralize } from 'lib/utils'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ActionFilter, CompareLabelType, FilterType, IntervalType } from '~/types'

import { formatBreakdownLabel } from '../utils'

export interface SeriesDatum {
    id: number // determines order that series will be displayed in
    dataIndex: number
    datasetIndex: number
    breakdown_value?: string | number
    compare_label?: CompareLabelType
    action?: ActionFilter
    label?: string
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
    entitiesAsColumnsOverride?: boolean
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
    hour: 'DD MMM YYYY HH:00',
    day: 'DD MMM YYYY',
    week: 'DD MMM YYYY',
    month: 'MMMM YYYY',
}

export function getFormattedDate(dayInput?: string | number, interval: IntervalType = 'day'): string {
    // Number of days
    if (Number.isInteger(dayInput)) {
        return pluralize(dayInput as number, 'day')
    }
    const day = dayjs(dayInput)
    // Dayjs formatted day
    if (dayInput !== undefined && day.isValid()) {
        return day.format(INTERVAL_UNIT_TO_DAYJS_FORMAT[interval])
    }
    return String(dayInput)
}

export function invertDataSource(seriesData: SeriesDatum[]): InvertedSeriesDatum[] {
    // NOTE: Assuming these logics are mounted elsewhere, and we're not interested in tracking changes.
    const cohorts = cohortsModel.findMounted()?.values?.cohorts
    const formatPropertyValueForDisplay = propertyDefinitionsModel.findMounted()?.values?.formatPropertyValueForDisplay
    const flattenedData: Record<string, InvertedSeriesDatum> = {}
    seriesData.forEach((s) => {
        let datumTitle
        const pillValues = []
        if (s.breakdown_value !== undefined) {
            pillValues.push(
                formatBreakdownLabel(
                    cohorts,
                    formatPropertyValueForDisplay,
                    s.breakdown_value,
                    s.filter?.breakdown,
                    s.filter?.breakdown_type,
                    s.filter && isTrendsFilter(s.filter) && s.filter?.breakdown_histogram_bin_count !== undefined
                )
            )
        }
        if (s.compare_label) {
            pillValues.push(capitalizeFirstLetter(String(s.compare_label)))
        }
        if (pillValues.length > 0) {
            datumTitle = (
                <>
                    {pillValues.map((pill) => (
                        <span key={pill}>{midEllipsis(pill, 60)}</span>
                    ))}
                </>
            )
        } else {
            // Technically should never reach this point because series data should have at least breakdown or compare values
            datumTitle = 'Baseline'
        }
        const datumKey = `${s.breakdown_value}-${s.compare_label}`
        if (datumKey in flattenedData) {
            flattenedData[datumKey].seriesData.push(s)
            flattenedData[datumKey].seriesData = flattenedData[datumKey].seriesData.sort(
                (a, b) => (b.action?.order ?? b.dataIndex) - (a.action?.order ?? a.dataIndex)
            )
        } else {
            flattenedData[datumKey] = {
                id: datumKey,
                datasetIndex: s.datasetIndex,
                color: s.color,
                datumTitle,
                seriesData: [s],
            }
        }
    })
    return Object.values(flattenedData)
}
