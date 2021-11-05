import React from 'react'
import { useActions, useValues } from 'kea'
import { ClockCircleOutlined, LineChartOutlined, FunnelPlotOutlined } from '@ant-design/icons'
import { FunnelVizType } from '~/types'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { DropdownSelector } from 'lib/components/DropdownSelector/DropdownSelector'
import { insightLogic } from 'scenes/insights/insightLogic'

interface ToggleButtonChartFilterProps {
    onChange?: (chartFilter: FunnelVizType) => void
    disabled?: boolean
}

const noop = (): void => {}

export function ToggleButtonChartFilter({
    onChange = noop,
    disabled = false,
}: ToggleButtonChartFilterProps): JSX.Element | null {
    const { insightProps, filters } = useValues(insightLogic)
    const { setFilters } = useActions(insightLogic)
    const { clickhouseFeaturesEnabled } = useValues(funnelLogic(insightProps))
    const defaultDisplay = FunnelVizType.Steps

    const options = [
        {
            key: FunnelVizType.Steps,
            label: 'Conversion steps',
            description: "Track users' progress between steps of the funnel",
            icon: <FunnelPlotOutlined />,
        },
        {
            key: FunnelVizType.TimeToConvert,
            label: 'Time to convert',
            description: 'Track how long it takes for users to convert',
            icon: <ClockCircleOutlined />,
            hidden: !clickhouseFeaturesEnabled,
        },
        {
            key: FunnelVizType.Trends,
            label: 'Historical trends',
            description: "Track how this funnel's conversion rate is trending over time",
            icon: <LineChartOutlined />,
            hidden: !clickhouseFeaturesEnabled,
        },
    ]

    if (options.filter((option) => !option.hidden).length <= 1) {
        return null
    }

    return (
        <div style={{ paddingBottom: '1rem' }}>
            <h4 className="secondary">Graph Type</h4>
            <div className="funnel-chart-filter">
                <DropdownSelector
                    options={options}
                    value={filters.funnel_viz_type || defaultDisplay}
                    onValueChange={(val) => {
                        const valueTyped = val as FunnelVizType
                        setFilters({ ...filters, funnel_viz_type: valueTyped })
                        onChange(valueTyped)
                    }}
                    disabled={disabled}
                    hideDescriptionOnDisplay
                />
            </div>
        </div>
    )
}
