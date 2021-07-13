import React from 'react'
import { Col, Row, Select } from 'antd'
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration, humanizeNumber } from 'lib/utils'
import { calcPercentage, getReferenceStep } from './funnelUtils'
import { funnelLogic } from './funnelLogic'
import { Histogram } from 'scenes/insights/Histogram'

export function FunnelHistogram(): JSX.Element {
    const { stepsWithCount, stepReference, histogramGraphData, histogramStepsDropdown, barGraphLayout } = useValues(
        funnelLogic
    )
    const { changeHistogramStep } = useActions(funnelLogic)
    // const dataset = [
    //     { data: histogramGraphData.personsAmount, labels: histogramGraphData.time, label: 'Time to convert' },
    // ]
    //
    console.log('datasets', histogramGraphData)

    return (
        <>
            <div>
                Steps
                {histogramStepsDropdown.length > 0 && (
                    <Select
                        defaultValue={histogramStepsDropdown[0]?.value}
                        onChange={changeHistogramStep}
                        dropdownMatchSelectWidth={false}
                        data-attr="funnel-bar-layout-selector"
                        optionLabelProp="label"
                        style={{ marginLeft: 8, marginBottom: 16 }}
                    >
                        {histogramStepsDropdown.map((option, i) => {
                            const basisStep = getReferenceStep(stepsWithCount, stepReference, i)
                            return (
                                <Select.Option
                                    key={option?.value}
                                    value={option?.value || 1}
                                    label={<>{option?.label}</>}
                                >
                                    <Col style={{ minWidth: 300 }}>
                                        <Row style={{ justifyContent: 'space-between', padding: '8px 0px' }}>
                                            <span className="l4">{option?.label}</span>
                                            <span className="text-muted-alt">
                                                Mean time: {humanFriendlyDuration(option?.average_conversion_time)}
                                            </span>
                                        </Row>
                                        <Row className="text-muted-alt">
                                            Total conversion rate:{' '}
                                            {humanizeNumber(calcPercentage(option.count, basisStep.count))}%
                                        </Row>
                                    </Col>
                                </Select.Option>
                            )
                        })}
                    </Select>
                )}
            </div>
            <Histogram data={histogramGraphData} layout={barGraphLayout} />
        </>
    )
}
