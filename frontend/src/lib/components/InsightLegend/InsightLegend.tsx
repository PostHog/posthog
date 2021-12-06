import './InsightLegend.scss'
import React from 'react'
import { Button, Row, Col } from 'antd'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LegendIcon } from 'lib/components/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightLabel } from 'lib/components/InsightLabel'
import { getChartColors } from 'lib/colors'
import { PHCheckbox } from 'lib/components/PHCheckbox'
import { formatCompareLabel } from 'scenes/insights/InsightsTable/InsightsTable'

export function InsightLegendButton(): JSX.Element {
    const { filters } = useValues(insightLogic)
    const { toggleInsightLegend } = useActions(insightLogic)

    return (
        <Button className="insight-legend-button" onClick={toggleInsightLegend}>
            <LegendIcon />
            <span className="insight-legend-button-title">{filters.legend_hidden ? 'Show' : 'Hide'} Legend</span>
        </Button>
    )
}

export function InsightLegend(): JSX.Element {
    const { insightProps, filters } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { indexedResults, visibilityMap } = useValues(logic)
    const { toggleVisibility } = useActions(logic)
    const colorList = getChartColors('white', indexedResults.length, !!filters.compare)

    return (
        <div className={clsx('insight-legend-menu', indexedResults.length <= 5 && 'short')}>
            {indexedResults &&
                indexedResults.map((item) => {
                    return (
                        <Row key={item.id} className="insight-legend-menu-item" wrap={false}>
                            <Col>
                                <PHCheckbox
                                    color={colorList[item.id]}
                                    checked={visibilityMap[item.id]}
                                    showIcon={indexedResults.length > 1}
                                    onChange={() => toggleVisibility(item.id)}
                                    disabled={indexedResults.length === 1}
                                />
                            </Col>
                            <Col>
                                <InsightLabel
                                    key={item.id}
                                    seriesColor={colorList[item.id]}
                                    action={item.action}
                                    fallbackName={item.breakdown_value === '' ? 'None' : item.label}
                                    hasMultipleSeries={indexedResults.length > 1}
                                    breakdownValue={
                                        item.breakdown_value === '' ? 'None' : item.breakdown_value?.toString()
                                    }
                                    compareValue={filters.compare ? formatCompareLabel(item) : undefined}
                                    hideIcon
                                    useCustomName
                                    hideSeriesSubtitle={false}
                                />
                            </Col>
                        </Row>
                    )
                })}
        </div>
    )
}
