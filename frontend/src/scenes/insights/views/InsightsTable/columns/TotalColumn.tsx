import { useValues, useActions } from 'kea'
import { Dropdown, Menu } from 'antd'
import { DownOutlined } from '@ant-design/icons'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

import { average, median } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { formatAggregationValue } from 'scenes/insights/utils'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { IndexedTrendResult } from 'scenes/trends/types'

import { CalcColumnState } from '../insightsTableLogic'
import { TrendsFilterType } from '~/types'
import { TrendsFilter } from '~/queries/schema'

const CALC_COLUMN_LABELS: Record<CalcColumnState, string> = {
    total: 'Total Sum',
    average: 'Average',
    median: 'Median',
}

type TotalColumnTitleProps = {
    isNonTimeSeriesDisplay: boolean
    calcColumnState: CalcColumnState
    setCalcColumnState: (state: CalcColumnState) => void
}

export function TotalColumnTitle({
    isNonTimeSeriesDisplay,
    calcColumnState,
    setCalcColumnState,
}: TotalColumnTitleProps): JSX.Element {
    const { reportInsightsTableCalcToggled } = useActions(eventUsageLogic)

    if (isNonTimeSeriesDisplay) {
        return <span>{CALC_COLUMN_LABELS.total}</span>
    }

    const calcColumnMenu = (
        <Menu>
            {Object.keys(CALC_COLUMN_LABELS).map((key) => (
                <Menu.Item
                    key={key}
                    onClick={(e) => {
                        setCalcColumnState(key as CalcColumnState)
                        reportInsightsTableCalcToggled(key)
                        e.domEvent.stopPropagation() // Prevent click here from affecting table sorting
                    }}
                >
                    {CALC_COLUMN_LABELS[key as CalcColumnState]}
                </Menu.Item>
            ))}
        </Menu>
    )
    return (
        <Dropdown overlay={calcColumnMenu}>
            <span className="cursor-pointer">
                {CALC_COLUMN_LABELS[calcColumnState]}
                <DownOutlined className="ml-1" />
            </span>
        </Dropdown>
    )
}

type TotalColumnItemProps = {
    item: IndexedTrendResult
    isNonTimeSeriesDisplay: boolean
    calcColumnState: CalcColumnState
    trendsFilter: TrendsFilter | null | undefined
}

export function TotalColumnItem({
    item,
    isNonTimeSeriesDisplay,
    calcColumnState,
    trendsFilter,
}: TotalColumnItemProps): JSX.Element {
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    let value: number | undefined = undefined
    if (calcColumnState === 'total' || isNonTimeSeriesDisplay) {
        value = item.count ?? item.aggregated_value
        if (item.aggregated_value > item.count) {
            value = item.aggregated_value
        }
    } else if (calcColumnState === 'average') {
        value = average(item.data)
    } else if (calcColumnState === 'median') {
        value = median(item.data)
    }

    return (
        <span>
            {value !== undefined
                ? formatAggregationValue(
                      item.action?.math_property,
                      value,
                      (value) => formatAggregationAxisValue(trendsFilter as Partial<TrendsFilterType>, value),
                      formatPropertyValueForDisplay
                  )
                : 'Unknown'}
        </span>
    )
}
