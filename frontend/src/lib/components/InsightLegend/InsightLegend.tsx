import './InsightLegend.scss'
import React from 'react'
import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { IconLegend } from 'lib/components/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightLabel } from 'lib/components/InsightLabel'
import { getSeriesColor } from 'lib/colors'
import { LemonCheckbox } from 'lib/components/LemonCheckbox'
import { formatCompareLabel } from 'scenes/insights/views/InsightsTable/InsightsTable'
import { ChartDisplayType, FilterType, InsightType } from '~/types'
import clsx from 'clsx'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'

export interface InsightLegendProps {
    readOnly?: boolean
    horizontal?: boolean
    inCardView?: boolean
}

const legendToggleDenyList = [
    ChartDisplayType.WorldMap,
    ChartDisplayType.ActionsTable,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.ActionsBarValue,
]

const shouldHideLegend = (filters: Partial<FilterType>, activeView: InsightType): boolean =>
    (filters.display && legendToggleDenyList.includes(filters.display)) || activeView === InsightType.STICKINESS

export function InsightLegendButton(): JSX.Element | null {
    const { filters, activeView } = useValues(insightLogic)
    const { toggleInsightLegend } = useActions(insightLogic)

    if (shouldHideLegend(filters, activeView)) {
        return null
    }

    return (
        <Button className="InsightLegendButton" onClick={toggleInsightLegend}>
            <IconLegend />
            <span className="InsightLegendButton-title">{filters.show_legend ? 'Hide' : 'Show'} legend</span>
        </Button>
    )
}

export function InsightLegend({ horizontal, inCardView, readOnly = false }: InsightLegendProps): JSX.Element | null {
    const { insightProps, filters, highlightedSeries, activeView } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { indexedResults, hiddenLegendKeys } = useValues(logic)
    const { toggleVisibility } = useActions(logic)

    if (shouldHideLegend(filters, activeView)) {
        return null
    }

    return (
        <div
            className={clsx('InsightLegendMenu', {
                'InsightLegendMenu--horizontal': horizontal,
                'InsightLegendMenu--readonly': readOnly,
                'InsightLegendMenu--in-card-view': inCardView,
            })}
        >
            <div className="InsightLegendMenu-scroll">
                {indexedResults &&
                    indexedResults.map((item, index) => {
                        const highlightStyle: Record<string, any> =
                            highlightedSeries === index
                                ? {
                                      style: { backgroundColor: getSeriesColor(item.id, false, true) },
                                  }
                                : {}

                        return (
                            <div key={item.id} className="InsightLegendMenu-item p-2 w-full flex flex-row">
                                <div
                                    key={item.id}
                                    className={clsx('InsightLegendMenu-item p-2 w-full flex flex-row')}
                                    {...highlightStyle}
                                >
                                    <LemonCheckbox
                                        className="text-xs mr-4"
                                        color={getSeriesColor(item.id, !!filters.compare)}
                                        checked={!hiddenLegendKeys[index]}
                                        onChange={() => toggleVisibility(index)}
                                        fullWidth
                                        label={
                                            <InsightLabel
                                                key={item.id}
                                                seriesColor={getSeriesColor(item.id, !!filters.compare)}
                                                action={item.action}
                                                fallbackName={item.breakdown_value === '' ? 'None' : item.label}
                                                hasMultipleSeries={indexedResults.length > 1}
                                                breakdownValue={
                                                    item.breakdown_value === ''
                                                        ? 'None'
                                                        : item.breakdown_value?.toString()
                                                }
                                                compareValue={filters.compare ? formatCompareLabel(item) : undefined}
                                                pillMidEllipsis={item?.filter?.breakdown === '$current_url'} // TODO: define set of breakdown values that would benefit from mid ellipsis truncation
                                                hideIcon
                                            />
                                        }
                                    />
                                    {filters.display === ChartDisplayType.ActionsPie && (
                                        <div className={'text-muted'}>
                                            {formatAggregationAxisValue(filters, item.aggregated_value)}
                                        </div>
                                    )}
                                </div>
                            </div>
                        )
                    })}
            </div>
        </div>
    )
}
