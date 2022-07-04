import React from 'react'
import { Input } from 'antd'
import { rollingDateRangeFilterLogic } from './rollingDateRangeFilterLogic'
import { useActions, useValues } from 'kea'
import { LemonButton, LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/components/Tooltip'
import { dayjs } from 'lib/dayjs'
import clsx from 'clsx'
import './RollingDateRangeFilter.scss'

const dateOptions: LemonSelectOptions = {
    days: {
        label: 'days',
    },
    weeks: {
        label: 'weeks',
    },
    months: {
        label: 'months',
    },
    quarter: {
        label: 'quarters',
    },
}

type RollingDateRangeFilterProps = {
    selected?: boolean
    dateFrom?: string | null | dayjs.Dayjs
    onChange?: (fromDate: string) => void
    makeLabel?: (key: React.ReactNode) => React.ReactNode
    popup?: {
        ref?: React.MutableRefObject<HTMLDivElement | null>
    }
}

export function RollingDateRangeFilter({
    onChange,
    makeLabel,
    popup,
    dateFrom,
    selected,
}: RollingDateRangeFilterProps): JSX.Element {
    const logicProps = { onChange, dateFrom, selected }
    const { increaseCounter, decreaseCounter, setCounter, setDateOption, toggleDateOptionsSelector, select } =
        useActions(rollingDateRangeFilterLogic(logicProps))
    const { counter, dateOption, isDateOptionsSelectorOpen, formattedDate } = useValues(
        rollingDateRangeFilterLogic(logicProps)
    )

    const onInputChange = (event: React.ChangeEvent<HTMLInputElement>): void => {
        const newValue = event.target.value ? parseFloat(event.target.value) : undefined
        setCounter(newValue)
    }

    return (
        <Tooltip title={makeLabel ? makeLabel(formattedDate) : undefined}>
            <div
                className={clsx('RollingDateRangeFilter', {
                    'RollingDateRangeFilter--selected': selected,
                })}
                data-attr="rolling-date-range-filter"
                onClick={select}
            >
                <p className="RollingDateRangeFilter__label">In the last</p>
                <div className="RollingDateRangeFilter__counter" onClick={(e): void => e.stopPropagation()}>
                    <LemonButton
                        onClick={decreaseCounter}
                        title={`Decrease rolling date range`}
                        type={'stealth'}
                        size="small"
                    >
                        -
                    </LemonButton>
                    <Input
                        data-attr="rolling-date-range-input"
                        type="number"
                        value={counter ?? ''}
                        min="0"
                        placeholder="0"
                        onChange={onInputChange}
                        bordered={false}
                    />
                    <LemonButton
                        onClick={increaseCounter}
                        title={`Increase rolling date range`}
                        type={'stealth'}
                        size="small"
                    >
                        +
                    </LemonButton>
                </div>
                <LemonSelect
                    className="RollingDateRangeFilter__select"
                    data-attr="rolling-date-range-date-options-selector"
                    id="rolling-date-range-date-options-selector"
                    value={dateOption}
                    onChange={(newValue): void => setDateOption(newValue as string)}
                    open={isDateOptionsSelectorOpen}
                    onClick={(e): void => {
                        e.stopPropagation()
                        toggleDateOptionsSelector()
                    }}
                    dropdownMatchSelectWidth={false}
                    options={dateOptions}
                    type="stealth"
                    popup={{
                        ...popup,
                        className: 'RollingDateRangeFilter__popup',
                    }}
                    outlined
                    size="small"
                />
            </div>
        </Tooltip>
    )
}
