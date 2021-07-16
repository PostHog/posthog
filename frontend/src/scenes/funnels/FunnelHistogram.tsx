import React, { useRef } from 'react'
import { Col, Row, Select } from 'antd'
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration, humanizeNumber } from 'lib/utils'
import { calcPercentage, getReferenceStep } from './funnelUtils'
import { funnelLogic } from './funnelLogic'
import { Histogram } from 'scenes/insights/Histogram'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ChartDisplayType } from '~/types'
import { useResponsiveWidth } from 'lib/hooks/useResponsiveWidth'
import { HISTOGRAM_WIDTH_BREAKPOINTS } from 'scenes/insights/Histogram/histogramUtils'

import './FunnelHistogram.scss'

export function FunnelHistogramHeader(): JSX.Element | null {
    const { stepsWithCount, stepReference, histogramStepsDropdown } = useValues(funnelLogic)
    const { changeHistogramStep } = useActions(funnelLogic)
    const { allFilters } = useValues(insightLogic)

    if (allFilters.display !== ChartDisplayType.FunnelsTimeToConvert) {
        return null
    }

    return (
        <div className="funnel__header__steps">
            <span className="funnel__header__steps__label">Steps</span>
            {histogramStepsDropdown.length > 0 && (
                <Select
                    defaultValue={histogramStepsDropdown[0]?.from_step}
                    onChange={(from_step) => {
                        changeHistogramStep(from_step, from_step + 1)
                    }}
                    dropdownMatchSelectWidth={false}
                    data-attr="funnel-bar-layout-selector"
                    optionLabelProp="label"
                >
                    {histogramStepsDropdown.map((option, i) => {
                        const basisStep = getReferenceStep(stepsWithCount, stepReference, i)
                        return (
                            <Select.Option
                                key={option?.from_step}
                                value={option?.from_step}
                                label={<>{option?.label}</>}
                            >
                                <Col style={{ minWidth: 300 }}>
                                    <Row style={{ justifyContent: 'space-between', padding: '8px 0px' }}>
                                        <span className="l4">{option?.label}</span>
                                        <span className="text-muted-alt">
                                            Mean time: {humanFriendlyDuration(option.average_conversion_time)}
                                        </span>
                                    </Row>
                                    <Row className="text-muted-alt">
                                        Total conversion rate:{' '}
                                        {humanizeNumber(calcPercentage(option.count || 0, basisStep.count))}
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
    const ref = useRef(null)

    // Funnel histogram specific sizing
    const widthToHeightRatio = useResponsiveWidth(ref, HISTOGRAM_WIDTH_BREAKPOINTS)

    console.log('WIDTH TO HEIGHT RATIO', widthToHeightRatio)

    return (
        <div className="funnel__histogram-wrapper" ref={ref}>
            <Histogram data={histogramGraphData} layout={barGraphLayout} widthToHeightRatio={widthToHeightRatio} />
        </div>
    )
}
