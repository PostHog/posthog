import { useValues } from 'kea'
import { DateDisplay } from 'lib/components/DateDisplay'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatAggregationValue } from 'scenes/insights/utils'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { IndexedTrendResult } from 'scenes/trends/types'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ResolvedDateRangeResponse, TrendsFilter } from '~/queries/schema/schema-general'
import { IntervalType, TrendsFilterType } from '~/types'

type ValueColumnTitleProps = {
    index: number
    indexedResults: IndexedTrendResult[]
    compare?: boolean | null
    interval?: IntervalType | null
    resolvedDateRange?: ResolvedDateRangeResponse
    timezone?: string
}

export function ValueColumnTitle({
    index,
    indexedResults,
    compare,
    interval,
    resolvedDateRange,
    timezone,
}: ValueColumnTitleProps): JSX.Element {
    const previousResult = compare ? indexedResults.find((r) => r.compare_label === 'previous') : undefined

    return (
        <DateDisplay
            interval={interval || 'day'}
            resolvedDateRange={resolvedDateRange}
            timezone={timezone}
            date={(indexedResults[0].dates || indexedResults[0].days)[index]} // current
            secondaryDate={previousResult ? (previousResult.dates || previousResult.days)[index] : undefined} // previous
            hideWeekRange
        />
    )
}

type ValueColumnItemProps = {
    index: number
    item: IndexedTrendResult
    trendsFilter: TrendsFilter | null | undefined
}

export function ValueColumnItem({ index, item, trendsFilter }: ValueColumnItemProps): JSX.Element {
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { insightProps } = useValues(insightLogic)
    const { isStickiness } = useValues(trendsDataLogic(insightProps))
    const formattedValue = formatAggregationValue(
        item.action?.math_property,
        item.data[index],
        (value) => formatAggregationAxisValue(trendsFilter as Partial<TrendsFilterType>, value),
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
}
