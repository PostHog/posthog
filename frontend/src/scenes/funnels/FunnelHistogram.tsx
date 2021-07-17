import React from 'react'
import { Col, Row, Select } from 'antd'
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration, humanizeNumber } from 'lib/utils'
import { calcPercentage, getReferenceStep } from './funnelUtils'
import { funnelLogic } from './funnelLogic'
import { Histogram } from 'scenes/insights/Histogram'
import { insightLogic } from 'scenes/insights/insightLogic'
import './FunnelHistogram.scss'
import { FUNNELS_TIME_TO_CONVERT } from 'lib/constants'

export function FunnelHistogramHeader(): JSX.Element | null {
    const { stepsWithCount, stepReference, histogramStepsDropdown } = useValues(funnelLogic)
    const { changeHistogramStep } = useActions(funnelLogic)
    const { allFilters } = useValues(insightLogic)

    if (allFilters.display !== FUNNELS_TIME_TO_CONVERT) {
        return null
    }

    return (
        <div className="funnel__header__steps">
            <span className="funnel__header__steps__label">Steps</span>
            {histogramStepsDropdown.length > 0 && stepsWithCount.length > 0 && (
                <Select
                    defaultValue={histogramStepsDropdown[0]?.value}
                    onChange={changeHistogramStep}
                    dropdownMatchSelectWidth={false}
                    data-attr="funnel-bar-layout-selector"
                    optionLabelProp="label"
                >
                    {histogramStepsDropdown.map((option, i) => {
                        const basisStep = getReferenceStep(stepsWithCount, stepReference, i)
                        return (
                            <Select.Option key={option?.value} value={option?.value || 1} label={<>{option?.label}</>}>
                                <Col style={{ minWidth: 300 }}>
                                    <Row style={{ justifyContent: 'space-between', padding: '8px 0px' }}>
                                        <span className="l4">{option?.label}</span>
                                        <span className="text-muted-alt">
                                            Mean time: {humanFriendlyDuration(option?.average_conversion_time)}
                                        </span>
                                    </Row>
                                    <Row className="text-muted-alt">
                                        Total conversion rate:{' '}
                                        {humanizeNumber(Math.round(calcPercentage(option.count, basisStep.count)))}%
                                    </Row>
                                </Col>
                            </Select.Option>
                        )
                    })}
                </Select>
            )}
        </div>
    )
}

export function FunnelHistogram(): JSX.Element {
    const { histogramGraphData, barGraphLayout } = useValues(funnelLogic)
    return (
        <>
            <Histogram data={histogramGraphData} layout={barGraphLayout} />
        </>
    )
}
