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
import { ChartDisplayType, InsightType } from '~/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import clsx from 'clsx'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'

export interface InsightLegendProps extends Pick<React.HTMLAttributes<HTMLDivElement>, 'className'> {
    readOnly?: boolean
    horizontal?: boolean
    inCardView?: boolean
}

export function InsightLegendButton(): JSX.Element | null {
    const { filters, activeView } = useValues(insightLogic)
    const { toggleInsightLegend } = useActions(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (
        !(
            ((activeView === InsightType.TRENDS &&
                filters.display !== ChartDisplayType.WorldMap &&
                filters.display !== ChartDisplayType.ActionsTable &&
                filters.display !== ChartDisplayType.BoldNumber) ||
                activeView === InsightType.STICKINESS) &&
            featureFlags[FEATURE_FLAGS.INSIGHT_LEGENDS]
        )
    ) {
        return null
    }

    return (
        <Button className="InsightLegendButton" onClick={toggleInsightLegend}>
            <IconLegend />
            <span className="InsightLegendButton-title">{filters.show_legend ? 'Hide' : 'Show'} legend</span>
        </Button>
    )
}

export function InsightLegend({
    horizontal,
    className,
    inCardView,
    readOnly = false,
}: InsightLegendProps): JSX.Element {
    const { insightProps, filters } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { indexedResults, hiddenLegendKeys } = useValues(logic)
    const { toggleVisibility } = useActions(logic)

    return (
        <div
            className={clsx('InsightLegendMenu', className, {
                'InsightLegendMenu--horizontal': horizontal,
                'InsightLegendMenu--readonly': readOnly,
                'InsightLegendMenu--in-card-view': inCardView,
            })}
        >
            <div className="InsightLegendMenu-scroll">
                {indexedResults &&
                    indexedResults
                        .sort((a, b) => b.aggregated_value - a.aggregated_value)
                        .map((item) => {
                            return (
                                <div key={item.id} className="InsightLegendMenu-item p-2 w-full flex flex-row">
                                    <LemonCheckbox
                                        className="text-xs mr-4"
                                        color={getSeriesColor(item.id, !!filters.compare)}
                                        checked={!hiddenLegendKeys[item.id]}
                                        onChange={() => toggleVisibility(item.id)}
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
                            )
                        })}
            </div>
        </div>
    )
}
