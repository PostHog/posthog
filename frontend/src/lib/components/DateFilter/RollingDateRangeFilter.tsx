import './RollingDateRangeFilter.scss'

import { useActions, useValues } from 'kea'

import { LemonButton, LemonButtonProps, LemonInput, LemonSelect, LemonSelectOptionLeaf } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { DateOption, rollingDateRangeFilterLogic } from './rollingDateRangeFilterLogic'

const dateOptions: LemonSelectOptionLeaf<DateOption>[] = [
    { value: 'minutes', label: 'minutes' },
    { value: 'hours', label: 'hours' },
    { value: 'days', label: 'days' },
    { value: 'weeks', label: 'weeks' },
    { value: 'months', label: 'months' },
    { value: 'quarters', label: 'quarters' },
    { value: 'years', label: 'years' },
]

type RollingDateRangeFilterProps = {
    isButton?: boolean
    pageKey?: string
    /** specifies if the filter is selected in the dropdown (to darken) */
    selected?: boolean
    /** specifies if the filter is in use (causes it to read props) */
    inUse?: boolean
    dateFrom?: string | null | dayjs.Dayjs
    max?: number | null
    onChange?: (fromDate: string) => void
    makeLabel?: (key: React.ReactNode, startOfRange?: React.ReactNode) => React.ReactNode
    popover?: {
        ref?: React.MutableRefObject<HTMLDivElement | null>
    }
    dateRangeFilterLabel?: string
    dateRangeFilterSuffixLabel?: string
    allowedDateOptions?: DateOption[]
    fullWidth?: LemonButtonProps['fullWidth']
}

export function RollingDateRangeFilter({
    isButton = true,
    onChange,
    makeLabel,
    popover,
    dateFrom,
    selected,
    inUse,
    max,
    dateRangeFilterLabel = 'In the last',
    dateRangeFilterSuffixLabel,
    pageKey,
    allowedDateOptions = ['days', 'weeks', 'months', 'years'],
    fullWidth,
}: RollingDateRangeFilterProps): JSX.Element {
    const logicProps = { onChange, dateFrom, inUse: selected || inUse, max, pageKey }
    const { increaseCounter, decreaseCounter, setCounter, setDateOption, toggleDateOptionsSelector, select } =
        useActions(rollingDateRangeFilterLogic(logicProps))
    const { counter, dateOption, formattedDate, startOfDateRange } = useValues(rollingDateRangeFilterLogic(logicProps))

    let contents = (
        <div className="flex items-center">
            <p className="RollingDateRangeFilter__label">{dateRangeFilterLabel}</p>
            <div className="RollingDateRangeFilter__counter" onClick={(e): void => e.stopPropagation()}>
                <span
                    className="RollingDateRangeFilter__counter__step cursor-pointer bg-transparent"
                    onClick={decreaseCounter}
                    title="Decrease rolling date range"
                >
                    -
                </span>
                <LemonInput
                    data-attr="rolling-date-range-input"
                    className="[&>input::-webkit-inner-spin-button]:appearance-none"
                    type="number"
                    value={counter ?? 0}
                    min={0}
                    placeholder="0"
                    onChange={(value) => setCounter(value)}
                />
                <span
                    className="RollingDateRangeFilter__counter__step cursor-pointer bg-transparent"
                    onClick={increaseCounter}
                    title="Increase rolling date range"
                >
                    +
                </span>
            </div>
            <LemonSelect
                className="RollingDateRangeFilter__select"
                data-attr="rolling-date-range-date-options-selector"
                id="rolling-date-range-date-options-selector"
                value={dateOption}
                onChange={(newValue): void => setDateOption(newValue)}
                onClick={(e): void => {
                    e.stopPropagation()
                    toggleDateOptionsSelector()
                }}
                dropdownMatchSelectWidth={false}
                options={dateOptions.filter((option) => allowedDateOptions.includes(option.value))}
                menu={{
                    ...popover,
                    className: 'RollingDateRangeFilter__popover',
                }}
                size="xsmall"
            />
            {dateRangeFilterSuffixLabel ? (
                <p className="RollingDateRangeFilter__label ml-1"> {dateRangeFilterSuffixLabel}</p>
            ) : null}
        </div>
    )

    if (isButton) {
        contents = (
            <LemonButton
                className="RollingDateRangeFilter"
                data-attr="rolling-date-range-filter"
                onClick={select}
                active={selected}
                fullWidth={fullWidth}
            >
                {contents}
            </LemonButton>
        )
    }

    if (makeLabel) {
        contents = <Tooltip title={makeLabel(formattedDate, startOfDateRange)}>{contents}</Tooltip>
    }

    return contents
}
