import React from 'react'
import { Select } from 'antd'
import { FundOutlined } from '@ant-design/icons'
import { defaultSmoothing, smoothings } from 'lib/components/SmoothingFilter/smoothings'
import { IntervalKeyType } from 'lib/components/IntervalFilter/intervals'
import { ViewType } from '~/types'

interface SmoothingFilterProps {
    view: ViewType
    interval: IntervalKeyType
    disabled?: boolean
}

const useSmoothing = (): void => {
    React.useState<string>('1')
}

export function SmoothingFilter({ view, interval, disabled }: SmoothingFilterProps): JSX.Element {
    const [smoothing, setSmoothing] = useSmoothing()
    const options = Object.entries(smoothings).map(([key, { label }]) => ({
        key,
        value: key,
        label:
            key === smoothing ? (
                <>
                    <FundOutlined /> {label}
                </>
            ) : (
                label
            ),
        disabled: (interval !== 'day' && view !== ViewType.TRENDS) || disabled,
    }))
    return (
        <Select
            bordered={false}
            disabled={disabled}
            defaultValue={smoothing || defaultSmoothing}
            value={smoothing || undefined}
            dropdownMatchSelectWidth={false}
            onChange={(key) => {
                setSmoothing(key)
            }}
            data-attr="smoothing-filter"
            options={options}
        />
    )
}
