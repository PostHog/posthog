import React from 'react'
import { useActions, useValues } from 'kea'
import { Dropdown, Menu, Button } from 'antd'
import { ChartDisplayType } from '~/types'
import { chartFilterLogic } from 'lib/components/ChartFilter/chartFilterLogic'
import { DownOutlined } from '@ant-design/icons'

interface ToggleButtonChartFilterProps {
    onChange?: (chartFilter: ChartDisplayType) => void
    disabled?: boolean
}

const noop = (): void => {}

export function ToggleButtonChartFilter({
    onChange = noop,
    disabled = false,
}: ToggleButtonChartFilterProps): JSX.Element {
    const logic = chartFilterLogic({ defaultChartFilter: ChartDisplayType.FunnelViz })
    const { chartFilter } = useValues(logic)
    const { setChartFilter } = useActions(logic)

    const options: { [key in ChartDisplayType]?: string } = {
        [ChartDisplayType.FunnelViz]: 'Funnel conversion',
        [ChartDisplayType.ActionsHistogramChart]: 'Time to convert',
        [ChartDisplayType.ActionsLineGraphLinear]: 'Conversion trend',
    }

    return (
        <Dropdown
            overlay={
                <Menu
                    onClick={({ key }) => {
                        const displayType = key as ChartDisplayType
                        setChartFilter(displayType)
                        onChange(displayType)
                    }}
                >
                    {Object.entries(options).map(([value, label]) => (
                        <Menu.Item key={value}>{label}</Menu.Item>
                    ))}
                </Menu>
            }
            trigger={['click']}
            data-attr="chart-filter"
            disabled={disabled}
        >
            <Button>
                {chartFilter ? options[chartFilter] : 'Select graph type'} <DownOutlined />
            </Button>
        </Dropdown>
    )
}
