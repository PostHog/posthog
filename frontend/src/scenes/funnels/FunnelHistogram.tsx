import React, { useRef } from 'react'
import { Col, Row, Select } from 'antd'
import { useActions, useValues } from 'kea'
import useSize from '@react-hook/size'
import { ANTD_TOOLTIP_PLACEMENTS, humanFriendlyDuration, humanizeNumber } from 'lib/utils'
import { calcPercentage, getReferenceStep } from './funnelUtils'
import { funnelLogic } from './funnelLogic'
import { Histogram } from 'scenes/insights/Histogram'
import { insightLogic } from 'scenes/insights/insightLogic'

import './FunnelHistogram.scss'
import { FunnelVizType } from '~/types'
import { ChartParams } from '~/types'

export function FunnelHistogramHeader(): JSX.Element | null {
    const { stepsWithCount, stepReference, histogramStepsDropdown } = useValues(funnelLogic)
    const { changeHistogramStep } = useActions(funnelLogic)
    const { allFilters } = useValues(insightLogic)

    if (allFilters.funnel_viz_type !== FunnelVizType.TimeToConvert) {
        return null
    }

    return (
        <div className="funnel-header-steps">
            <span className="funnel-header-steps-label">Steps</span>
            {histogramStepsDropdown.length > 0 && stepsWithCount.length > 0 && (
                <Select
                    defaultValue={histogramStepsDropdown[0]?.from_step}
                    onChange={(from_step) => {
                        changeHistogramStep(from_step, from_step + 1)
                    }}
                    dropdownMatchSelectWidth={false}
                    dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                    data-attr="funnel-bar-layout-selector"
                    optionLabelProp="label"
                >
                    {histogramStepsDropdown.map((option, i) => {
                        const basisStep = getReferenceStep(stepsWithCount, stepReference, i)
                        return (
                            <Select.Option key={option.from_step} value={option.from_step} label={<>{option?.label}</>}>
                                <Col style={{ minWidth: 300 }}>
                                    <Row style={{ justifyContent: 'space-between', padding: '8px 0px' }}>
                                        <span className="l4">{option?.label}</span>
                                        <span className="text-muted-alt">
                                            Average time: {humanFriendlyDuration(option.average_conversion_time)}
                                        </span>
                                    </Row>
                                    <Row className="text-muted-alt">
                                        Total conversion rate:{' '}
                                        {humanizeNumber(Math.round(calcPercentage(option.count ?? 0, basisStep.count)))}
                                        %
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

export function FunnelHistogram({ filters, dashboardItemId }: Omit<ChartParams, 'view'>): JSX.Element {
    const logic = funnelLogic({ dashboardItemId, filters })
    const { histogramGraphData } = useValues(logic)
    const ref = useRef(null)
    const [width] = useSize(ref)

    return (
        <div ref={ref}>
            <Histogram data={histogramGraphData} width={width} />
        </div>
    )
}
