import './RollingDateRangeFilter.scss'

import { LemonButton, LemonInput, LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { DateOption, rollingDateRangeFilterLogic } from './rollingDateRangeFilterLogic'

const dateOptions: LemonSelectOptions<DateOption> = [
    { value: 'days', label: 'days' },
    { value: 'weeks', label: 'weeks' },
    { value: 'months', label: 'months' },
    { value: 'quarters', label: 'quarters' },
]

type RollingDateRangeFilterProps = {
    pageKey?: string
    selected?: boolean
    dateFrom?: string | null | dayjs.Dayjs
    max?: number | null
    onChange?: (fromDate: string) => void
    makeLabel?: (key: React.ReactNode, startOfRange?: React.ReactNode) => React.ReactNode
    popover?: {
        ref?: React.MutableRefObject<HTMLDivElement | null>
    }
    dateRangeFilterLabel?: string
    /* By default, we only update default counter values when selected, because that's the preferred way in insights.
     * However, in some cases, we want to update the default counter values even when not selected, like
     * when inside a TaxonomicFilter component.
     */
    forceUpdateDefaults?: boolean
}

export function RollingDateRangeFilter({
    onChange,
    makeLabel,
    popover,
    dateFrom,
    selected,
    max,
    dateRangeFilterLabel = 'In the last',
    forceUpdateDefaults,
    pageKey,
}: RollingDateRangeFilterProps): JSX.Element {
    const logicProps = { onChange, dateFrom, selected, max, forceUpdateDefaults, pageKey }
    const { increaseCounter, decreaseCounter, setCounter, setDateOption, toggleDateOptionsSelector, select } =
        useActions(rollingDateRangeFilterLogic(logicProps))
    const { counter, dateOption, formattedDate, startOfDateRange } = useValues(rollingDateRangeFilterLogic(logicProps))

    return (
        <Tooltip title={makeLabel ? makeLabel(formattedDate, startOfDateRange) : undefined}>
            <LemonButton
                className="RollingDateRangeFilter"
                data-attr="rolling-date-range-filter"
                onClick={select}
                active={selected}
            >
                <p className="RollingDateRangeFilter__label">{dateRangeFilterLabel}</p>
                <div className="RollingDateRangeFilter__counter" onClick={(e): void => e.stopPropagation()}>
                    <span
                        className="RollingDateRangeFilter__counter__step"
                        onClick={decreaseCounter}
                        title="Decrease rolling date range"
                    >
                        -
                    </span>
                    <LemonInput
                        data-attr="rolling-date-range-input"
                        type="number"
                        value={counter ?? 0}
                        min={0}
                        placeholder="0"
                        onChange={(value) => setCounter(value)}
                    />
                    <span
                        className="RollingDateRangeFilter__counter__step"
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
                    options={dateOptions}
                    menu={{
                        ...popover,
                        className: 'RollingDateRangeFilter__popover',
                    }}
                    size="xsmall"
                />
            </LemonButton>
        </Tooltip>
    )
}
