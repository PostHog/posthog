import { Placement } from '@floating-ui/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonDivider, Popover } from '@posthog/lemon-ui'

import {
    CUSTOM_OPTION_DESCRIPTION,
    CUSTOM_OPTION_KEY,
    DateFilterLogicProps,
    DateFilterView,
    NO_OVERRIDE_RANGE_PLACEHOLDER,
} from 'lib/components/DateFilter/types'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelect, LemonCalendarSelectProps } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonCalendarRange } from 'lib/lemon-ui/LemonCalendarRange/LemonCalendarRange'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { dateFilterToText, dateMapping, uuid } from 'lib/utils'

import { DateMappingOption, PropertyOperator } from '~/types'

import { PropertyFilterDatePicker } from '../PropertyFilters/components/PropertyFilterDatePicker'
import { RollingDateRangeFilter } from './RollingDateRangeFilter'
import { dateFilterLogic } from './dateFilterLogic'
import { DateOption } from './rollingDateRangeFilterLogic'

export interface DateFilterProps {
    showCustom?: boolean
    showRollingRangePicker?: boolean
    makeLabel?: (key: React.ReactNode, startOfRange?: React.ReactNode) => React.ReactNode
    className?: string
    onChange?: (fromDate: string | null, toDate: string | null, explicitDate?: boolean) => void
    disabled?: boolean
    disabledReason?: string | null
    dateOptions?: DateMappingOption[]
    isDateFormatted?: boolean
    size?: LemonButtonProps['size']
    type?: LemonButtonProps['type']
    dropdownPlacement?: Placement
    /* True when we're not dealing with ranges, but a single date / relative date */
    isFixedDateMode?: boolean
    placeholder?: string
    fullWidth?: boolean
}

interface RawDateFilterProps extends DateFilterProps {
    dateFrom?: string | null | dayjs.Dayjs
    dateTo?: string | null | dayjs.Dayjs
    max?: number | null
    allowedRollingDateOptions?: DateOption[]
    allowTimePrecision?: boolean
    /**
     * Granularity is picked based on the dateFrom value
     * but can be overridden to force a specific granularity.
     * For example, set to 'day' to never show the time picker.
     */
    forceGranularity?: LemonCalendarSelectProps['granularity']
}

export function DateFilter({
    showCustom,
    showRollingRangePicker = true,
    className,
    disabledReason,
    makeLabel,
    onChange,
    dateFrom,
    dateTo,
    dateOptions = dateMapping,
    isDateFormatted = true,
    size,
    type,
    dropdownPlacement = 'bottom-start',
    max,
    isFixedDateMode = false,
    allowedRollingDateOptions,
    allowTimePrecision = false,
    placeholder,
    fullWidth = false,
    forceGranularity,
}: RawDateFilterProps): JSX.Element {
    const key = useRef(uuid()).current
    const logicProps: DateFilterLogicProps = {
        key,
        dateFrom,
        dateTo,
        onChange,
        dateOptions,
        isDateFormatted,
        isFixedDateMode,
        placeholder,
        allowTimePrecision,
    }
    const {
        open,
        openFixedRange,
        openDateToNow,
        openFixedDate,
        close,
        setRangeDateFrom,
        setExplicitDate,
        setRangeDateTo,
        setDate,
        applyRange,
    } = useActions(dateFilterLogic(logicProps))
    const {
        isVisible,
        view,
        rangeDateFrom,
        rangeDateTo,
        label,
        isFixedRange,
        isDateToNow,
        isFixedDate,
        isRollingDateRange,
        dateFromHasTimePrecision,
    } = useValues(dateFilterLogic(logicProps))

    const optionsRef = useRef<HTMLDivElement | null>(null)
    const rollingDateRangeRef = useRef<HTMLDivElement | null>(null)
    const [granularity, setGranularity] = useState<LemonCalendarSelectProps['granularity']>(
        forceGranularity ?? (dateFromHasTimePrecision ? 'minute' : 'day')
    )

    const popoverOverlay =
        view === DateFilterView.FixedRange ? (
            <LemonCalendarRange
                value={[rangeDateFrom ?? dayjs(), rangeDateTo ?? dayjs()]}
                onChange={([from, to]) => {
                    setRangeDateFrom(from)
                    setRangeDateTo(to)
                    setExplicitDate(false)
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
                    setExplicitDate(granularity === 'minute')
                    applyRange()
                }}
                onClose={open}
                granularity={forceGranularity ?? granularity}
                showTimeToggle={forceGranularity ? false : allowTimePrecision}
                onToggleTime={
                    forceGranularity ? undefined : () => setGranularity(granularity === 'minute' ? 'day' : 'minute')
                }
            />
        ) : view === DateFilterView.FixedDate ? (
            <PropertyFilterDatePicker
                autoFocus
                operator={PropertyOperator.Exact}
                value={rangeDateFrom ? rangeDateFrom.toString() : dayjs().toString()}
                setValue={(date) => {
                    setDate(String(date), '')
                }}
            />
        ) : (
            <div className="deprecated-space-y-px" ref={optionsRef} onClick={(e) => e.stopPropagation()}>
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
                    const startOfRangeDateValue = dateFilterToText(
                        values[0],
                        undefined,
                        '',
                        [],
                        false,
                        'MMMM D, YYYY',
                        true
                    )

                    return (
                        <Tooltip key={key} title={makeLabel ? makeLabel(dateValue, startOfRangeDateValue) : undefined}>
                            <LemonButton
                                key={key}
                                onClick={() => setDate(values[0] || null, values[1] || null)}
                                active={isActive}
                                fullWidth
                            >
                                {key === CUSTOM_OPTION_KEY ? NO_OVERRIDE_RANGE_PLACEHOLDER : key}
                            </LemonButton>
                        </Tooltip>
                    )
                })}
                {showRollingRangePicker && (
                    <RollingDateRangeFilter
                        pageKey={key}
                        dateFrom={dateFrom}
                        dateRangeFilterLabel={isFixedDateMode ? 'Last' : undefined}
                        selected={isRollingDateRange}
                        onChange={(fromDate) => {
                            setDate(fromDate, '', true)
                        }}
                        makeLabel={makeLabel}
                        popover={{
                            ref: rollingDateRangeRef,
                        }}
                        max={max}
                        allowedDateOptions={
                            isFixedDateMode && !allowedRollingDateOptions
                                ? ['hours', 'days', 'weeks', 'months', 'years']
                                : allowedRollingDateOptions
                        }
                        fullWidth
                    />
                )}
                <LemonDivider />
                {isFixedDateMode ? (
                    <LemonButton onClick={openFixedDate} active={isFixedDate} fullWidth>
                        Custom date...
                    </LemonButton>
                ) : (
                    <>
                        <LemonButton onClick={openDateToNow} active={isDateToNow} fullWidth>
                            From custom date until now…
                        </LemonButton>
                        <LemonButton onClick={openFixedRange} active={isFixedRange} fullWidth>
                            Custom fixed date range…
                        </LemonButton>
                    </>
                )}
            </div>
        )

    return (
        <Popover
            visible={isVisible}
            overlay={popoverOverlay}
            placement={dropdownPlacement}
            actionable
            additionalRefs={[rollingDateRangeRef]}
            onClickOutside={close}
            closeParentPopoverOnClickInside={false}
        >
            <LemonButton
                id="daterange_selector"
                size={size ?? 'small'}
                type={type ?? 'secondary'}
                disabledReason={disabledReason}
                data-attr="date-filter"
                icon={<IconCalendar />}
                onClick={isVisible ? close : open}
                fullWidth={fullWidth}
            >
                <span className={clsx('text-nowrap', className)}>{label}</span>
            </LemonButton>
        </Popover>
    )
}
