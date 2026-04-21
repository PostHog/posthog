import './AggregationColumn.scss'

import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonMenu, LemonMenuItem } from '@posthog/lemon-ui'

import { average, median } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { formatAggregationValue } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { IndexedTrendResult } from 'scenes/trends/types'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { TrendsFilter } from '~/queries/schema/schema-general'
import { TrendsFilterType } from '~/types'

import { CalcColumnState } from '../InsightsTable'

export const CALC_COLUMN_LABELS: Record<CalcColumnState, string> = {
    total: 'Total Sum',
    average: 'Average',
    median: 'Median',
}

type AggregationColumnTitleProps = {
    isNonTimeSeriesDisplay: boolean
    aggregation: CalcColumnState
    setAggregationType: (state: CalcColumnState) => void
}

export function AggregationColumnTitle({
    isNonTimeSeriesDisplay,
    aggregation,
    setAggregationType,
}: AggregationColumnTitleProps): JSX.Element {
    const { reportInsightsTableCalcToggled } = useActions(eventUsageLogic)

    if (isNonTimeSeriesDisplay) {
        return <span>{CALC_COLUMN_LABELS.total}</span>
    }

    const items: LemonMenuItem[] = Object.entries(CALC_COLUMN_LABELS).map(([key, label]) => ({
        label,
        onClick: () => {
            setAggregationType(key as CalcColumnState)
            reportInsightsTableCalcToggled(key)
        },
    }))

    return (
        <LemonMenu items={items}>
            <span
                className="AggregationColumn__title LemonTable__header--no-hover flex cursor-pointer whitespace-nowrap"
                onClick={(e) => {
                    e.stopPropagation()
                }}
            >
                {CALC_COLUMN_LABELS[aggregation]}
                <IconChevronDown className="text-lg" />
            </span>
        </LemonMenu>
    )
}

type AggregationColumnItemProps = {
    item: IndexedTrendResult
    isNonTimeSeriesDisplay: boolean
    aggregation: CalcColumnState
    trendsFilter: TrendsFilter | null | undefined
}

export function getAggregatedValue(
    item: IndexedTrendResult,
    aggregation: CalcColumnState,
    isNonTimeSeriesDisplay: boolean
): number | undefined {
    if (aggregation === 'total' || isNonTimeSeriesDisplay) {
        let value = item.count ?? item.aggregated_value
        if (item.aggregated_value > item.count || (item.aggregated_value < 0 && item.aggregated_value < item.count)) {
            value = item.aggregated_value
        }
        return value
    } else if (aggregation === 'average') {
        return average(item.data)
    } else if (aggregation === 'median') {
        return median(item.data)
    }
    return undefined
}

export function AggregationColumnItem({
    item,
    isNonTimeSeriesDisplay,
    aggregation,
    trendsFilter,
}: AggregationColumnItemProps): JSX.Element {
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { baseCurrency } = useValues(teamLogic)

    const value = getAggregatedValue(item, aggregation, isNonTimeSeriesDisplay)

    const formattedValue: ReactNode =
        value !== undefined
            ? formatAggregationValue(
                  item.action?.math_property,
                  value,
                  (value) => formatAggregationAxisValue(trendsFilter as Partial<TrendsFilterType>, value, baseCurrency),
                  formatPropertyValueForDisplay
              )
            : 'Unknown'

    return <span>{formattedValue}</span>
}
