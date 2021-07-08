import { Select } from 'antd'
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration } from 'lib/utils'
import React from 'react'
import { LineGraph } from 'scenes/insights/LineGraph'
import { funnelLogic } from './funnelLogic'

export function FunnelHistogram(): JSX.Element {
    const { timeConversionBins, stepsWithCount } = useValues(funnelLogic)
    const { changeHistogramStep } = useActions(funnelLogic)
    const labels = timeConversionBins.map((bin) => humanFriendlyDuration(`${bin[0]}`))
    const binData = timeConversionBins.map((bin) => bin[1])
    const dataset = [{ data: binData, labels: labels, label: 'Time to convert', count: 3 }]

    const stepsDropdown = []
    stepsWithCount.forEach((step, idx) => {
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
                        defaultValue={stepsDropdown[0]?.label}
                        // value={barGraphLayout || FunnelBarLayout.vertical}
                        onChange={changeHistogramStep}
                        bordered={false}
                        dropdownMatchSelectWidth={false}
                        data-attr="funnel-bar-layout-selector"
                        optionLabelProp="label"
                    >
                        <Select.OptGroup label="Graph display options">
                            {stepsDropdown.map((option) => (
                                <Select.Option
                                    key={option?.value}
                                    value={option?.value || 1}
                                    label={<>{option?.label}</>}
                                >
                                    {option?.label}
                                </Select.Option>
                            ))}
                        </Select.OptGroup>
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
