import { ReactNode, memo } from 'react'

import { DateDisplay } from 'lib/components/DateDisplay'
import { formatAggregationValue } from 'scenes/insights/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { FormatPropertyValueForDisplayFunction } from '~/models/propertyDefinitionsModel'
import { ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

type ValueColumnTitleProps = {
    index: number
    indexedResults: IndexedTrendResult[]
    compare?: boolean | null
    interval?: IntervalType | null
    resolvedDateRange?: ResolvedDateRangeResponse
    timezone?: string
    weekStartDay?: number
}

export function ValueColumnTitle({
    index,
    indexedResults,
    compare,
    interval,
    resolvedDateRange,
    timezone,
    weekStartDay,
}: ValueColumnTitleProps): JSX.Element {
    const previousResult = compare ? indexedResults.find((r) => r.compare_label === 'previous') : undefined

    return (
        <DateDisplay
            interval={interval || 'day'}
            resolvedDateRange={resolvedDateRange}
            timezone={timezone}
            weekStartDay={weekStartDay}
            date={(indexedResults[0].dates || indexedResults[0].days)[index]} // current
            secondaryDate={previousResult ? (previousResult.dates || previousResult.days)[index] : undefined} // previous
            hideWeekRange
        />
    )
}

type ValueColumnItemProps = {
    index: number
    item: IndexedTrendResult
    isStickiness: boolean
    renderCount: (value: number) => ReactNode
    formatPropertyValueForDisplay: FormatPropertyValueForDisplayFunction
}

export const ValueColumnItem = memo(function ValueColumnItem({
    index,
    item,
    isStickiness,
    renderCount,
    formatPropertyValueForDisplay,
}: ValueColumnItemProps): JSX.Element {
    const formattedValue = formatAggregationValue(
        item.action?.math_property,
        item.data[index],
        renderCount,
        formatPropertyValueForDisplay
    )
    return (
        <span>
            {isStickiness ? (
                <div>
                    <div>{item.count ? ((item.data[index] / item.count) * 100).toFixed(1) : '0'}%</div>
                    <div>({formattedValue})</div>
                </div>
            ) : (
                formattedValue
            )}
        </span>
    )
})
