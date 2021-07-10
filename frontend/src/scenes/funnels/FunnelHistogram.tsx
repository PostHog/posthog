import { Col, Row, Select } from 'antd'
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration, humanizeNumber } from 'lib/utils'
import React from 'react'
import { LineGraph } from 'scenes/insights/LineGraph'
import { calcPercentage, getReferenceStep } from './FunnelBarGraph'
import { funnelLogic } from './funnelLogic'

interface TimeStepOption {
    label: string
    value: number
    average_conversion_time: number
    count: number
}

export function FunnelHistogram(): JSX.Element {
    const { timeConversionBins, stepsWithCount, stepReference } = useValues(funnelLogic)
    const { changeHistogramStep } = useActions(funnelLogic)
    const labels = timeConversionBins.map((bin) => humanFriendlyDuration(`${bin[0]}`))
    const binData = timeConversionBins.map((bin) => bin[1])
    const dataset = [{ data: binData, labels: labels, label: 'Time to convert', count: 3 }]

    const stepsDropdown: TimeStepOption[] = []
    stepsWithCount.forEach((_, idx) => {
        if (stepsWithCount[idx + 1]) {
            stepsDropdown.push({
                label: `Steps ${idx + 1} and ${idx + 2}`,
                value: idx + 1,
                count: stepsWithCount[idx + 1].count,
                average_conversion_time: stepsWithCount[idx + 1].average_conversion_time,
            })
        }
    })

    return (
        <>
            <div>
                Steps
                {stepsDropdown.length > 0 && (
                    <Select
                        defaultValue={stepsDropdown[0]?.value}
                        onChange={changeHistogramStep}
                        dropdownMatchSelectWidth={false}
                        data-attr="funnel-bar-layout-selector"
                        optionLabelProp="label"
                        style={{ marginLeft: 8, marginBottom: 16 }}
                    >
                        {stepsDropdown.map((option, i) => {
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
                                            <span className="text-muted-alt-light">
                                                Average time: {humanFriendlyDuration(option?.average_conversion_time)}
                                            </span>
                                        </Row>
                                        <Row className="text-muted-alt-light">
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
            <LineGraph
                data-attr="funnels-histogram"
                type="bar"
                color={'white'}
                datasets={dataset}
                labels={labels}
                dashboardItemId={null}
            />
        </>
    )
}
