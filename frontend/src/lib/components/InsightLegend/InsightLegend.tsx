import './InsightLegend.scss'
import React from 'react'
import { Button, Row, Col } from 'antd'
import { useActions, useValues } from 'kea'
import { LegendIcon } from 'lib/components/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightLabel } from 'lib/components/InsightLabel'
import { getChartColors } from 'lib/colors'
import { PHCheckbox } from 'lib/components/PHCheckbox'

export function InsightLegendButton(): JSX.Element {
    const { filters } = useValues(insightLogic)
    const { setFilters } = useActions(insightLogic)

    console.log('FILTERS', filters.legend_visible)

    return (
        <Button
            className="insight-legend-button"
            onClick={() => setFilters({ legend_visible: !filters.legend_visible })}
        >
            <LegendIcon />
            <span className="insight-legend-button-title">{filters.legend_visible ? 'Hide' : 'Show'} Legend</span>
        </Button>
    )
}

export function InsightLegend(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { indexedResults, visibilityMap } = useValues(logic)
    const { toggleVisibility } = useActions(logic)

    console.log('RESULTS', indexedResults)
    const colorList = getChartColors('white')

    return (
        <div className="insight-legend-menu">
            {indexedResults &&
                indexedResults.map((item) => {
                    return (
                        <Row key={item.id} className="insight-legend-menu-item" wrap={false}>
                            <Col>
                                <PHCheckbox
                                    color={colorList[item.id]}
                                    checked={visibilityMap[item.id]}
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
