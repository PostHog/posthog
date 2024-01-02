import { Placement } from '@floating-ui/react'
import { LemonButton, LemonButtonProps, LemonButtonWithDropdown, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import {
    CUSTOM_OPTION_DESCRIPTION,
    CUSTOM_OPTION_KEY,
    CUSTOM_OPTION_VALUE,
    DateFilterLogicProps,
    DateFilterView,
} from 'lib/components/DateFilter/types'
import { dayjs } from 'lib/dayjs'
import { IconCalendar } from 'lib/lemon-ui/icons'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonCalendarRange } from 'lib/lemon-ui/LemonCalendarRange/LemonCalendarRange'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { dateFilterToText, dateMapping, uuid } from 'lib/utils'
import { useRef } from 'react'

import { DateMappingOption } from '~/types'

import { dateFilterLogic } from './dateFilterLogic'
import { RollingDateRangeFilter } from './RollingDateRangeFilter'

export interface DateFilterProps {
    showCustom?: boolean
    showRollingRangePicker?: boolean
    makeLabel?: (key: React.ReactNode) => React.ReactNode
    className?: string
    onChange?: (fromDate: string | null, toDate: string | null) => void
    disabled?: boolean
    dateOptions?: DateMappingOption[]
    isDateFormatted?: boolean
    size?: LemonButtonProps['size']
    dropdownPlacement?: Placement
}
interface RawDateFilterProps extends DateFilterProps {
    dateFrom?: string | null | dayjs.Dayjs
    dateTo?: string | null | dayjs.Dayjs
    max?: number | null
}

export function DateFilter({
    showCustom,
    showRollingRangePicker = true,
    className,
    disabled,
    makeLabel,
    onChange,
    dateFrom,
    dateTo,
    dateOptions = dateMapping,
    isDateFormatted = true,
    size,
    dropdownPlacement = 'bottom-start',
    max,
}: RawDateFilterProps): JSX.Element {
    const key = useRef(uuid()).current
    const logicProps: DateFilterLogicProps = {
        key,
        dateFrom,
        dateTo,
        onChange,
        dateOptions,
        isDateFormatted,
    }
    const { open, openFixedRange, openDateToNow, close, setRangeDateFrom, setRangeDateTo, setDate, applyRange } =
        useActions(dateFilterLogic(logicProps))
    const { isVisible, view, rangeDateFrom, rangeDateTo, label, isFixedRange, isDateToNow, isRollingDateRange } =
        useValues(dateFilterLogic(logicProps))

    const optionsRef = useRef<HTMLDivElement | null>(null)
    const rollingDateRangeRef = useRef<HTMLDivElement | null>(null)

    const popoverOverlay =
        view === DateFilterView.FixedRange ? (
            <LemonCalendarRange
                value={[rangeDateTo ?? dayjs(), rangeDateTo ?? dayjs()]}
                onChange={([from, to]) => {
                    setRangeDateFrom(from)
                    setRangeDateTo(to)
                    applyRange()
                }}
                onClose={open}
                months={2}
            />
        ) : view === DateFilterView.DateToNow ? (
            <LemonCalendarSelect
                value={rangeDateFrom ?? dayjs()}
                onChange={(date) => {
                    setRangeDateFrom(date)
                    setRangeDateTo(null)
                    applyRange()
                }}
                onClose={open}
            />
        ) : (
            <div className="space-y-px" ref={optionsRef} onClick={(e) => e.stopPropagation()}>
                {dateOptions.map(({ key, values, inactive }) => {
                    if (key === CUSTOM_OPTION_KEY && !showCustom) {
                        return null
                    }

                    if (inactive && label !== key) {
                        return null
                    }

                    const isActive =
                        (dateFrom ?? null) === (values[0] ?? null) && (dateTo ?? null) === (values[1] ?? null)
                    const dateValue = dateFilterToText(
                        values[0],
                        values[1],
                        CUSTOM_OPTION_DESCRIPTION,
                        dateOptions,
                        isDateFormatted
                    )

                    return (
                        <Tooltip key={key} title={makeLabel ? makeLabel(dateValue) : undefined}>
                            <LemonButton
                                key={key}
                                onClick={() => setDate(values[0] || null, values[1] || null)}
                                active={isActive}
                                fullWidth
                            >
                                {key === CUSTOM_OPTION_KEY ? CUSTOM_OPTION_VALUE : key}
                            </LemonButton>
                        </Tooltip>
                    )
                })}
                {showRollingRangePicker && (
                    <RollingDateRangeFilter
                        dateFrom={dateFrom}
                        selected={isRollingDateRange}
                        onChange={(fromDate) => {
                            setDate(fromDate, '')
                        }}
                        makeLabel={makeLabel}
                        popover={{
                            ref: rollingDateRangeRef,
                        }}
                        max={max}
                    />
                )}
                <LemonDivider />
                <LemonButton onClick={openDateToNow} active={isDateToNow} fullWidth>
                    From custom date until now…
                </LemonButton>
                <LemonButton onClick={openFixedRange} active={isFixedRange} fullWidth>
                    Custom fixed date range…
                </LemonButton>
            </div>
        )

    return (
        <LemonButtonWithDropdown
            data-attr="date-filter"
            id="daterange_selector"
            onClick={isVisible ? close : open}
            disabled={disabled}
            className={className}
            size={size ?? 'small'}
            type="secondary"
            dropdown={{
                onClickOutside: close,
                visible: isVisible,
                overlay: popoverOverlay,
                placement: dropdownPlacement,
                actionable: true,
                closeOnClickInside: false,
                additionalRefs: [rollingDateRangeRef, '.datefilter-datepicker'],
            }}
            icon={<IconCalendar />}
        >
            {label}
        </LemonButtonWithDropdown>
    )
}
