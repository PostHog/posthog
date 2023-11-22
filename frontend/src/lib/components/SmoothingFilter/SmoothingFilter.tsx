// eslint-disable-next-line no-restricted-imports
import { FundOutlined } from '@ant-design/icons'
import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { smoothingOptions } from './smoothings'

export function SmoothingFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { isTrends, interval, trendsFilter } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

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
        <LemonSelect
            key={interval}
            value={smoothing_intervals || 1}
            dropdownMatchSelectWidth={false}
            onChange={(key) => {
                updateInsightFilter({
                    smoothing_intervals: key,
                })
            }}
            data-attr="smoothing-filter"
            options={options}
            size="small"
        />
    ) : (
        <></>
    )
}
