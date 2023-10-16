import { Select } from 'antd'
import { FundOutlined } from '@ant-design/icons'
import { smoothingOptions } from './smoothings'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizLogic } from 'scenes/insights/insightVizLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

export function SmoothingFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { isTrends, interval, trendsFilter } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizLogic(insightProps))

    if (!isTrends || !interval) {
        return null
    }

    const { smoothing_intervals } = trendsFilter || {}

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
