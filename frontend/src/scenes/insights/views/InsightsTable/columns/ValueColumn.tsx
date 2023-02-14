import { IndexedTrendResult } from 'scenes/trends/types'
import { DateDisplay } from 'lib/components/DateDisplay'
import { IntervalType, TrendsFilterType } from '~/types'
import { formatAggregationValue } from 'scenes/insights/utils'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { useValues } from 'kea'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

type ValueColumnTitleProps = {
    index: number
    indexedResults: IndexedTrendResult[]
    compare?: boolean
    interval?: IntervalType
}

export function ValueColumnTitle({ index, indexedResults, compare, interval }: ValueColumnTitleProps): JSX.Element {
    const previousResult = compare ? indexedResults.find((r) => r.compare_label === 'previous') : undefined

    return (
        <DateDisplay
            interval={interval || 'day'}
            date={(indexedResults[0].dates || indexedResults[0].days)[index]} // current
            secondaryDate={!!previousResult ? (previousResult.dates || previousResult.days)[index] : undefined} // previous
            hideWeekRange
        />
    )
}

type ValueColumnItemProps = {
    index: number
    item: IndexedTrendResult
    filters: Partial<TrendsFilterType> | undefined
}

export function ValueColumnItem({ index, item, filters }: ValueColumnItemProps): JSX.Element {
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    return (
        <span>
            {formatAggregationValue(
                item.action?.math_property,
                item.data[index],
                (value) => formatAggregationAxisValue(filters, value),
                formatPropertyValueForDisplay
            )}
        </span>
    )
}
