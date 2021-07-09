import { Select } from 'antd'
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration } from 'lib/utils'
import React from 'react'
import { LineGraph } from 'scenes/insights/LineGraph'
import { funnelLogic } from './funnelLogic'

interface TimeStepOption {
    label: string
    value: number
}

export function FunnelHistogram(): JSX.Element {
    const { timeConversionBins, stepsWithCount } = useValues(funnelLogic)
    const { changeHistogramStep } = useActions(funnelLogic)
    const labels = timeConversionBins.map((bin) => humanFriendlyDuration(`${bin[0]}`))
    const binData = timeConversionBins.map((bin) => bin[1])
    const dataset = [{ data: binData, labels: labels, label: 'Time to convert', count: 3 }]

    const stepsDropdown: TimeStepOption[] = []
    stepsWithCount.forEach((_, idx) => {
        if (stepsWithCount[idx + 1]) {
            stepsDropdown.push({ label: `Steps ${idx + 1} and ${idx + 2}`, value: idx + 1 })
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
                        {stepsDropdown.map((option) => (
                            <Select.Option key={option?.value} value={option?.value || 1} label={<>{option?.label}</>}>
                                {option?.label}
                            </Select.Option>
                        ))}
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
