import { Select } from 'antd'
import { FundOutlined } from '@ant-design/icons'
import { smoothingOptions } from './smoothings'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'

export function SmoothingFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(trendsLogic(insightProps))
    const { setFilters } = useActions(trendsLogic(insightProps))
    const { interval, smoothing_intervals } = filters

    if (!interval) {
        return null
    }

    // Put a little icon next to the selected item
    const options = smoothingOptions[interval].map(({ value, label }) => ({
        value,
        label:
            value === smoothing_intervals ? (
                <>
                    <FundOutlined /> {label}
                </>
            ) : (
                label
            ),
    }))

    return options.length ? (
        <Select
            key={interval}
            bordered
            value={smoothing_intervals || 1}
            dropdownMatchSelectWidth={false}
            onChange={(key) => {
                setFilters({ ...filters, smoothing_intervals: key })
            }}
            data-attr="smoothing-filter"
            options={options}
        />
    ) : (
        <></>
    )
}
