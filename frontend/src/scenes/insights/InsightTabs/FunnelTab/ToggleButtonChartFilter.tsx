import React from 'react'
import { useActions, useValues } from 'kea'
import { Radio, Tooltip } from 'antd'
import { FunnelVizType } from '~/types'
import { chartFilterLogic } from 'lib/components/ChartFilter/chartFilterLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'

interface ToggleButtonChartFilterProps {
    onChange?: (chartFilter: FunnelVizType) => void
    disabled?: boolean
}

const noop = (): void => {}

export function ToggleButtonChartFilter({
    onChange = noop,
    disabled = false,
}: ToggleButtonChartFilterProps): JSX.Element {
    const { clickhouseFeaturesEnabled } = useValues(funnelLogic())
    const { chartFilter } = useValues(chartFilterLogic)
    const { setChartFilter } = useActions(chartFilterLogic)
    const defaultDisplay = FunnelVizType.Steps

    const options = [
        {
            value: FunnelVizType.Steps,
            label: <Tooltip title="Track users' progress between steps of the funnel">Conversion steps</Tooltip>,
            visible: true,
        },
        {
            value: FunnelVizType.TimeToConvert,
            label: <Tooltip title="Track how long it takes for users to convert">Time to convert</Tooltip>,
            visible: clickhouseFeaturesEnabled,
        },
        {
            value: FunnelVizType.Trends,
            label: <Tooltip title="Track how this funnel's conversion rate is trending over time">Historical</Tooltip>,
            visible: true,
        },
    ]

    return (
        <Radio.Group
            key="2"
            defaultValue={defaultDisplay}
            value={chartFilter || defaultDisplay}
            onChange={({ target: { value } }: { target: { value?: FunnelVizType } }) => {
                if (value) {
                    setChartFilter(value)
                    onChange(value)
                }
            }}
            data-attr="chart-filter"
            disabled={disabled}
            options={options.filter((o) => o.visible)}
            optionType="button"
            size="small"
        />
    )
}
