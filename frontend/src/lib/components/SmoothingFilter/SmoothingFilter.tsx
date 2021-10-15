import React from 'react'
import { Select } from 'antd'
import { FundOutlined } from '@ant-design/icons'
import { smoothingOptions } from './smoothings'
import { IntervalType } from '~/types'
import { intervalFilterLogic } from '../IntervalFilter/intervalFilterLogic'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

export function SmoothingFilter(): JSX.Element | null {
    const interval = useInterval()
    const [smoothing, setSmoothing] = useSmoothing()

    if (interval === null) {
        return null
    }

    // Put a little icon next to the selected item
    const options = smoothingOptions[interval].map(({ value, label }) => ({
        value,
        label:
            value === smoothing ? (
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
            bordered={false}
            value={smoothing || undefined}
            dropdownMatchSelectWidth={false}
            onChange={(key) => {
                setSmoothing(key)
            }}
            data-attr="smoothing-filter"
            options={options}
        />
    ) : (
        <></>
    )
}

const useSmoothing = (): [number, (value: number) => void] => {
    // Gets smoothing_interals from the url, along with a setter that can be
    // used to update it
    const {
        searchParams,
        location: { pathname },
        hashParams,
    } = useValues(router)
    const { replace } = useActions(router)
    const interval = useInterval()

    const setSmoothing = (smoothing: number): void => {
        replace(pathname, { ...searchParams, smoothing_intervals: smoothing }, hashParams)
    }

    const { smoothing_intervals = 1 } = searchParams

    // Check that the option is valid for the specified interval, and if not, set it to 1
    const intervalOptions = interval ? smoothingOptions[interval] : []

    React.useEffect(() => {
        if (!intervalOptions.find((option) => option.value === smoothing_intervals)) {
            setSmoothing(1)
        }
    }, [interval, smoothing_intervals])

    return [Number.parseInt(smoothing_intervals), setSmoothing]
}

const useInterval = (): IntervalType | null => {
    // Just proxies through to the interval filter logic to retrieve the
    // interval value
    const { interval } = useValues(intervalFilterLogic)
    return interval
}
