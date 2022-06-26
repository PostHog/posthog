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
import { formatCompareLabel } from 'scenes/insights/Views/InsightsTable/InsightsTable'
import { ChartDisplayType, InsightType } from '~/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import clsx from 'clsx'

export interface InsightLegendProps {
    readOnly?: boolean
    horizontal?: boolean
}

export function InsightLegendButton(): JSX.Element | null {
    const { filters, activeView } = useValues(insightLogic)
    const { toggleInsightLegend } = useActions(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (
        !(
            ((activeView === InsightType.TRENDS &&
                filters.display !== ChartDisplayType.WorldMap &&
                filters.display !== ChartDisplayType.ActionsTable) ||
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

export function InsightLegend({ horizontal, readOnly = false }: InsightLegendProps): JSX.Element {
    const { insightProps, filters } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { indexedResults, hiddenLegendKeys } = useValues(logic)
    const { toggleVisibility } = useActions(logic)

    return (
        <div
            className={clsx('InsightLegendMenu', {
                'InsightLegendMenu--horizontal': horizontal,
                'InsightLegendMenu--readonly': readOnly,
            })}
        >
            <div className="InsightLegendMenu-scroll">
                {indexedResults &&
                    indexedResults.map((item) => {
                        return (
                            <div key={item.id} className="InsightLegendMenu-item">
                                <LemonCheckbox
                                    className="InsightLegendMenu-item-inner"
                                    color={getSeriesColor(item.id, !!filters.compare)}
                                    checked={!hiddenLegendKeys[item.id]}
                                    onChange={() => toggleVisibility(item.id)}
                                    rowProps={{ fullWidth: true }}
                                    label={
                                        <InsightLabel
                                            key={item.id}
                                            seriesColor={getSeriesColor(item.id, !!filters.compare)}
                                            action={item.action}
                                            fallbackName={item.breakdown_value === '' ? 'None' : item.label}
                                            hasMultipleSeries={indexedResults.length > 1}
                                            breakdownValue={
                                                item.breakdown_value === '' ? 'None' : item.breakdown_value?.toString()
                                            }
                                            compareValue={filters.compare ? formatCompareLabel(item) : undefined}
                                            pillMidEllipsis={item?.filter?.breakdown === '$current_url'} // TODO: define set of breakdown values that would benefit from mid ellipsis truncation
                                            hideIcon
                                        />
                                    }
                                />
                            </div>
                        )
                    })}
            </div>
        </div>
    )
}
