import { Select } from 'antd'
import { FundOutlined } from '@ant-design/icons'
import { smoothingOptions } from './smoothings'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

export function SmoothingFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(trendsLogic(insightProps))
    const { setFilters } = useActions(trendsLogic(insightProps))
    const { updateInsightFilter } = useActions(insightDataLogic(insightProps))

    if (!filters.interval || !isTrendsFilter(filters)) {
        return null
    }

    const { interval, smoothing_intervals } = filters

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
                updateInsightFilter({
                    smoothing_intervals: key,
                })
            }}
            data-attr="smoothing-filter"
            options={options}
        />
    ) : (
        <></>
    )
}
