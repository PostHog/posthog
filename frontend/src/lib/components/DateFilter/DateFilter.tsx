import { Placement } from '@floating-ui/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { forwardRef, useRef, useState } from 'react'

import { IconCalendar, IconInfo } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonDivider, LemonSwitch, Popover } from '@posthog/lemon-ui'

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
import { formatResolvedDateRange } from 'lib/utils/dateTimeUtils'

import { ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import { DateMappingOption, PropertyOperator } from '~/types'

import { PropertyFilterDatePicker } from '../PropertyFilters/components/PropertyFilterDatePicker'
import { FixedRangeWithTimePicker } from './FixedRangeWithTimePicker'
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
    resolvedDateRange?: ResolvedDateRangeResponse
}

interface RawDateFilterProps extends DateFilterProps {
    dateFrom?: string | null | dayjs.Dayjs
    dateTo?: string | null | dayjs.Dayjs
    max?: number | null
    allowedRollingDateOptions?: DateOption[]
    allowTimePrecision?: boolean
    allowFixedRangeWithTime?: boolean
    /**
     * Granularity is picked based on the dateFrom value
     * but can be overridden to force a specific granularity.
     * For example, set to 'day' to never show the time picker.
     */
    forceGranularity?: LemonCalendarSelectProps['granularity']
    /** Use 24-hour format instead of 12-hour with AM/PM */
    use24HourFormat?: boolean
    explicitDate?: boolean
    showExplicitDateToggle?: boolean
}

export const DateFilter = forwardRef<HTMLButtonElement, RawDateFilterProps>(function DateFilter(
    {
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
        allowFixedRangeWithTime = false,
        placeholder,
        fullWidth = false,
        forceGranularity,
        use24HourFormat = false,
        explicitDate,
        showExplicitDateToggle = false,
        resolvedDateRange,
    },
    ref
) {
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
        explicitDate,
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
        setFixedRangeGranularity,
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
        fixedRangeGranularity,
    } = useValues(dateFilterLogic(logicProps))

    const optionsRef = useRef<HTMLDivElement | null>(null)
    const rollingDateRangeRef = useRef<HTMLDivElement | null>(null)
    const [granularity, setGranularity] = useState<LemonCalendarSelectProps['granularity']>(
        forceGranularity ?? (dateFromHasTimePrecision ? 'minute' : 'day')
    )

    const showFixedRangeTimeToggle = allowTimePrecision || allowFixedRangeWithTime

    const popoverOverlay =
        view === DateFilterView.FixedRange ? (
            fixedRangeGranularity === 'minute' ? (
                <FixedRangeWithTimePicker
                    rangeDateFrom={rangeDateFrom}
                    rangeDateTo={rangeDateTo}
                    setDate={setDate}
                    onClose={open}
                    use24HourFormat={use24HourFormat}
                    showTimeToggle={showFixedRangeTimeToggle}
                    onToggleTime={(includeTime) => setFixedRangeGranularity(includeTime ? 'minute' : 'day')}
                />
            ) : (
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
                    showTimeToggle={showFixedRangeTimeToggle}
                    onToggleTime={(includeTime) => setFixedRangeGranularity(includeTime ? 'minute' : 'day')}
                />
            )
        ) : view === DateFilterView.FixedRangeWithTime ? (
            <FixedRangeWithTimePicker
                rangeDateFrom={rangeDateFrom}
                rangeDateTo={rangeDateTo}
                setDate={setDate}
                onClose={open}
                use24HourFormat={use24HourFormat}
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
                use24HourFormat={use24HourFormat}
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
                                onClick={() => setDate(values[0] || null, values[1] || null, false, explicitDate)}
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
                            setDate(fromDate, '', true, explicitDate)
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
                {showExplicitDateToggle && (
                    <>
                        <LemonDivider />
                        <div className="LemonSwitch pb-2 pt-2 LemonSwitch--medium LemonSwitch--full-width">
                            <label className="flex items-center gap-1">
                                <span>Exact time range</span>
                                <Tooltip
                                    title={
                                        <>
                                            <div className="font-semibold mb-1">When enabled:</div>
                                            <div className="mb-2">
                                                Uses the current time for period boundaries instead of full days.
                                            </div>
                                            <div className="font-semibold mb-1">When disabled:</div>
                                            <div>Dates are rounded to full day periods (start and end of day).</div>
                                        </>
                                    }
                                >
                                    <IconInfo className="text-muted-alt w-4 h-4" />
                                </Tooltip>
                            </label>
                            <LemonSwitch
                                checked={explicitDate ?? false}
                                onChange={(checked) => {
                                    setExplicitDate(checked)
                                }}
                            />
                        </div>
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
                ref={ref}
                id="daterange_selector"
                size={size ?? 'small'}
                type={type ?? 'secondary'}
                disabledReason={disabledReason}
                data-attr="date-filter"
                icon={<IconCalendar />}
                onClick={isVisible ? close : open}
                fullWidth={fullWidth}
                tooltip={formatResolvedDateRange(resolvedDateRange)}
            >
                <span className={clsx('text-nowrap', className)}>{label}</span>
            </LemonButton>
        </Popover>
    )
})
