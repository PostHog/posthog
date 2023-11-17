import { Input } from 'antd'
import { DateOption, rollingDateRangeFilterLogic } from './rollingDateRangeFilterLogic'
import { useActions, useValues } from 'kea'
import { LemonButton, LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { dayjs } from 'lib/dayjs'
import clsx from 'clsx'
import './RollingDateRangeFilter.scss'

const dateOptions: LemonSelectOptions<DateOption> = [
    { value: 'days', label: 'days' },
    { value: 'weeks', label: 'weeks' },
    { value: 'months', label: 'months' },
    { value: 'quarters', label: 'quarters' },
]

type RollingDateRangeFilterProps = {
    selected?: boolean
    dateFrom?: string | null | dayjs.Dayjs
    max?: number | null
    onChange?: (fromDate: string) => void
    makeLabel?: (key: React.ReactNode) => React.ReactNode
    popover?: {
        ref?: React.MutableRefObject<HTMLDivElement | null>
    }
}

export function RollingDateRangeFilter({
    onChange,
    makeLabel,
    popover,
    dateFrom,
    selected,
    max,
}: RollingDateRangeFilterProps): JSX.Element {
    const logicProps = { onChange, dateFrom, selected, max }
    const { increaseCounter, decreaseCounter, setCounter, setDateOption, toggleDateOptionsSelector, select } =
        useActions(rollingDateRangeFilterLogic(logicProps))
    const { counter, dateOption, formattedDate } = useValues(rollingDateRangeFilterLogic(logicProps))

    const onInputChange = (event: React.ChangeEvent<HTMLInputElement>): void => {
        const newValue = event.target.value ? parseFloat(event.target.value) : undefined
        setCounter(newValue)
    }

    return (
        <Tooltip title={makeLabel ? makeLabel(formattedDate) : undefined}>
            <LemonButton
                className={clsx('RollingDateRangeFilter')}
                data-attr="rolling-date-range-filter"
                onClick={select}
                status="stealth"
                active={selected}
            >
                <p className="RollingDateRangeFilter__label">In the last</p>
                <div className="RollingDateRangeFilter__counter" onClick={(e): void => e.stopPropagation()}>
                    <span
                        className="RollingDateRangeFilter__counter__step"
                        onClick={decreaseCounter}
                        title={`Decrease rolling date range`}
                    >
                        -
                    </span>
                    <Input
                        data-attr="rolling-date-range-input"
                        type="number"
                        value={counter ?? ''}
                        min="0"
                        placeholder="0"
                        onChange={onInputChange}
                        bordered={false}
                    />
                    <span
                        className="RollingDateRangeFilter__counter__step"
                        onClick={increaseCounter}
                        title={`Increase rolling date range`}
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
                    size="small"
                />
            </LemonButton>
        </Tooltip>
    )
}
