import React from 'react'
import { Input } from 'antd'
import { rollingDateRangeFilterLogic } from './RollingDateRangeFilterLogic'
import { useActions, useValues } from 'kea'
import { LemonButton, LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/components/Tooltip'

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
        label: 'quarter',
    },
}

type RollingDateRangeFilterProps = {
    onChange?: (fromDate: string, toDate: string) => void
    makeLabel?: (key: React.ReactNode) => React.ReactNode
    popupRef?: React.MutableRefObject<HTMLDivElement | null>
}

export function RollingDateRangeFilter({ onChange, makeLabel, popupRef }: RollingDateRangeFilterProps): JSX.Element {
    const { increaseCounter, decreaseCounter, setCounter, setDateOption, toggleDateOptionsSelector } =
        useActions(rollingDateRangeFilterLogic)
    const { counter, dateOption, isDateOptionsSelectorOpen, formattedDate, dateFrom, dateTo } =
        useValues(rollingDateRangeFilterLogic)

    const onInputChange = (event: React.ChangeEvent<HTMLInputElement>): void => {
        const newValue = event.target.value ? parseFloat(event.target.value) : undefined
        setCounter(newValue)
    }

    return (
        <Tooltip title={makeLabel ? makeLabel(formattedDate) : undefined}>
            <div
                className="custom-range-button rolling-date-range-filter"
                data-attr="rolling-date-range-filter"
                onClick={(): void => onChange && onChange(dateFrom, dateTo)}
            >
                <p className="label">In the last</p>
                <div className="date-selector-input" onClick={(e): void => e.stopPropagation()}>
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
                        className="numeric-input"
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
                    className="date-options-selector"
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
                    popupClassName="rolling-date-range-options-selector-popup"
                    popupRef={popupRef}
                    outlined
                    size="small"
                />
            </div>
        </Tooltip>
    )
}
