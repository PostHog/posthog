import { useValues } from 'kea'
import { DateDisplay } from 'lib/components/DateDisplay'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { formatAggregationValue } from 'scenes/insights/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { TrendsFilter } from '~/queries/schema'
import { IntervalType, TrendsFilterType } from '~/types'

type ValueColumnTitleProps = {
    index: number
    indexedResults: IndexedTrendResult[]
    compare?: boolean | null
    interval?: IntervalType | null
}

export function ValueColumnTitle({ index, indexedResults, compare, interval }: ValueColumnTitleProps): JSX.Element {
    const previousResult = compare ? indexedResults.find((r) => r.compare_label === 'previous') : undefined

    return (
        <DateDisplay
            interval={interval || 'day'}
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
    return (
        <span>
            {formatAggregationValue(
                item.action?.math_property,
                item.data[index],
                (value) => formatAggregationAxisValue(trendsFilter as Partial<TrendsFilterType>, value),
                formatPropertyValueForDisplay
            )}
        </span>
    )
}
