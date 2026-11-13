import { useActions, useValues } from 'kea'
import { Fragment, forwardRef, useEffect, useRef, useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import {
    Button,
    CUSTOM_RANGE,
    DatePicker,
    DateTimePicker,
    ItemRadio,
    Popover,
    PopoverContent,
    PopoverTrigger,
    SelectTriggerIcon,
    Separator,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { QuillChartOptionSwitch } from 'lib/components/ChartOptions/QuillChartOptionSwitch'
import {
    CUSTOM_OPTION_DESCRIPTION,
    DateFilterView,
    NO_OVERRIDE_RANGE_PLACEHOLDER,
} from 'lib/components/DateFilter/types'
import { dayjs } from 'lib/dayjs'
import { CUSTOM_OPTION_KEY, dateFilterToText, dateMapping } from 'lib/utils/dateFilters'
import { formatResolvedDateRange } from 'lib/utils/datetime'
import { uuid } from 'lib/utils/dom'
import { teamLogic } from 'scenes/teamLogic'

import type { RawDateFilterProps } from './DateFilter'
import { DateFilterExclusionsControl } from './DateFilterExclusionsControl'
import { dateFilterLogic } from './dateFilterLogic'
import { RelativeRangeInput, type RelativeRangeUnit } from './RelativeRangeInput'
import { rollingDateRangeFilterLogic } from './rollingDateRangeFilterLogic'

export interface QuillDateFilterMenuProps extends Pick<
    RawDateFilterProps,
    | 'showCustom'
    | 'dateFrom'
    | 'dateTo'
    | 'onChange'
    | 'dateOptions'
    | 'makeLabel'
    | 'disabledReason'
    | 'resolvedDateRange'
    | 'onOpenChange'
    | 'max'
    | 'allowTimePrecision'
    | 'allowFixedRangeWithTime'
    | 'explicitDate'
    | 'showExplicitDateToggle'
    | 'exclusions'
    | 'onExclusionsChange'
    | 'showIncompletePeriodExclusion'
    | 'showDaysOfWeekExclusions'
> {
    allowedRollingDateOptions?: RelativeRangeUnit[]
}

export const QuillDateFilterMenu = forwardRef<HTMLButtonElement, QuillDateFilterMenuProps>(function QuillDateFilterMenu(
    {
        showCustom = false,
        dateFrom,
        dateTo,
        onChange,
        dateOptions = dateMapping,
        makeLabel,
        disabledReason,
        resolvedDateRange,
        onOpenChange,
        max,
        allowTimePrecision = false,
        allowFixedRangeWithTime = false,
        explicitDate,
        showExplicitDateToggle = false,
        exclusions,
        onExclusionsChange,
        showIncompletePeriodExclusion = false,
        showDaysOfWeekExclusions = false,
        allowedRollingDateOptions = ['days', 'weeks', 'months', 'years'],
    },
    ref
) {
    const key = useRef(uuid()).current
    const logic = dateFilterLogic({
        key,
        dateFrom,
        dateTo,
        onChange,
        dateOptions,
        isDateFormatted: true,
        isFixedDateMode: false,
        allowTimePrecision,
        explicitDate,
    })
    const {
        open,
        openFixedRange,
        openDateToNow,
        close,
        setDate,
        setRangeDateFrom,
        setRangeDateTo,
        setExplicitDate,
        applyRange,
        setFixedRangeGranularity,
    } = useActions(logic)
    const {
        isVisible,
        view,
        label,
        rangeDateFrom,
        rangeDateTo,
        isFixedRange,
        isDateToNow,
        isRollingDateRange,
        dateFromHasTimePrecision,
        fixedRangeGranularity,
    } = useValues(logic)
    const { weekStartDay } = useValues(teamLogic)

    const rollingLogic = rollingDateRangeFilterLogic({
        pageKey: key,
        dateFrom,
        max,
        inUse: isRollingDateRange,
        onChange: (fromDate) => setDate(fromDate, '', true, explicitDate),
    })
    const { counter, dateOption, formattedDate, startOfDateRange } = useValues(rollingLogic)
    const { setCounter, setDateOption, select } = useActions(rollingLogic)

    const [dateToNowWithTime, setDateToNowWithTime] = useState(dateFromHasTimePrecision)

    const onOpenChangeRef = useRef(onOpenChange)
    useEffect(() => {
        onOpenChangeRef.current = onOpenChange
    })
    const wasVisibleRef = useRef(isVisible)
    useEffect(() => {
        if (isVisible !== wasVisibleRef.current) {
            wasVisibleRef.current = isVisible
            onOpenChangeRef.current?.(isVisible)
        }
    }, [isVisible])

    const showFixedRangeTimeToggle = allowTimePrecision || allowFixedRangeWithTime
    const fixedRangeWithTime = showFixedRangeTimeToggle && fixedRangeGranularity === 'minute'
    const showExclusions =
        (showIncompletePeriodExclusion || showDaysOfWeekExclusions) && !!exclusions && !!onExclusionsChange

    const withTooltip = (row: JSX.Element, title: React.ReactNode): JSX.Element =>
        title ? (
            <Tooltip>
                <TooltipTrigger render={row} />
                <TooltipContent side="right">{title}</TooltipContent>
            </Tooltip>
        ) : (
            row
        )

    const quickList = (
        <div role="radiogroup" aria-label="Date range" className="flex flex-col">
            <div className="flex max-h-80 flex-col gap-px overflow-y-auto p-1 scroll-mask-y-4 scroll-py-4">
                {dateOptions.map(({ key: optionKey, values, inactive }) => {
                    if ((optionKey === CUSTOM_OPTION_KEY && !showCustom) || (inactive && label !== optionKey)) {
                        return null
                    }
                    const isActive =
                        (dateFrom ?? null) === (values[0] ?? null) && (dateTo ?? null) === (values[1] ?? null)
                    const row = (
                        <ItemRadio
                            size="xs"
                            aria-checked={isActive}
                            // pinned: data-attr values feed autocapture dashboards and tests
                            data-attr={`date-filter-${optionKey.toLowerCase().replace(/\s+/g, '-')}`}
                            onClick={() => setDate(values[0] || null, values[1] || null, false, explicitDate)}
                        >
                            {optionKey === CUSTOM_OPTION_KEY ? NO_OVERRIDE_RANGE_PLACEHOLDER : optionKey}
                        </ItemRadio>
                    )
                    return (
                        <Fragment key={optionKey}>
                            {withTooltip(
                                row,
                                makeLabel?.(
                                    dateFilterToText(
                                        values[0],
                                        values[1],
                                        CUSTOM_OPTION_DESCRIPTION,
                                        dateOptions,
                                        true,
                                        undefined,
                                        undefined,
                                        weekStartDay
                                    ),
                                    dateFilterToText(values[0], undefined, '', [], false, 'MMMM D, YYYY', true),
                                    values[1]
                                        ? dateFilterToText(values[1], undefined, '', [], false, 'MMMM D, YYYY', true)
                                        : undefined
                                )
                            )}
                        </Fragment>
                    )
                })}
                <div className="flex items-center gap-1">
                    {withTooltip(
                        <ItemRadio
                            size="xs"
                            aria-checked={isRollingDateRange}
                            className="w-auto shrink-0"
                            data-attr="rolling-date-range-filter"
                            onClick={select}
                        >
                            In the last
                        </ItemRadio>,
                        makeLabel?.(formattedDate, startOfDateRange)
                    )}
                    <RelativeRangeInput
                        value={{ count: counter ?? 1, unit: dateOption as RelativeRangeUnit }}
                        onChange={({ count, unit }) => {
                            if (unit !== dateOption) {
                                setDateOption(unit)
                            } else {
                                setCounter(count)
                            }
                        }}
                        units={allowedRollingDateOptions}
                        max={max ?? undefined}
                    />
                </div>
            </div>
            <Separator />
            <div className="flex flex-col gap-px p-1">
                <ItemRadio size="xs" aria-checked={isDateToNow} onClick={openDateToNow}>
                    From custom date until now…
                </ItemRadio>
                <ItemRadio size="xs" aria-checked={isFixedRange} onClick={openFixedRange}>
                    Custom fixed date range…
                </ItemRadio>
            </div>
            {(showExplicitDateToggle || showExclusions) && (
                <>
                    <Separator />
                    <div className="flex flex-col gap-1 p-1">
                        {showExplicitDateToggle && (
                            <div className="px-2 py-1">
                                <QuillChartOptionSwitch
                                    label="Exact time range"
                                    info="When enabled, uses the current time for period boundaries instead of full days. When disabled, dates are rounded to full day periods (start and end of day)."
                                    checked={explicitDate ?? false}
                                    onChange={setExplicitDate}
                                />
                            </div>
                        )}
                        {showExclusions && (
                            <DateFilterExclusionsControl
                                exclusions={exclusions}
                                onChange={onExclusionsChange}
                                showDays={showDaysOfWeekExclusions}
                                showIncomplete={showIncompletePeriodExclusion}
                            />
                        )}
                    </div>
                </>
            )}
        </div>
    )

    const fixedRange = (
        <div className="flex flex-col">
            {showFixedRangeTimeToggle && (
                <div className="border-b border-border px-3 py-1.5">
                    <QuillChartOptionSwitch
                        label="Include time"
                        checked={fixedRangeWithTime}
                        onChange={(includeTime) => setFixedRangeGranularity(includeTime ? 'minute' : 'day')}
                    />
                </div>
            )}
            <DateTimePicker
                // The picker reads `value` at mount only, so remount it when time is switched on or off
                key={fixedRangeWithTime ? 'time' : 'day'}
                ranges={[]}
                showHeader={false}
                showTime={fixedRangeWithTime}
                weekStartsOn={weekStartDay === 1 ? 1 : 0}
                value={{
                    start: (rangeDateFrom ?? dayjs()).toDate(),
                    end: (rangeDateTo ?? dayjs()).toDate(),
                    range: CUSTOM_RANGE,
                }}
                onApply={({ start, end }) => {
                    if (fixedRangeWithTime) {
                        setDate(
                            dayjs(start).format('YYYY-MM-DDTHH:mm:ss'),
                            dayjs(end).format('YYYY-MM-DDTHH:mm:ss'),
                            false,
                            true
                        )
                        return
                    }
                    setRangeDateFrom(dayjs(start).startOf('day'))
                    setRangeDateTo(dayjs(end).endOf('day'))
                    setExplicitDate(false)
                    applyRange()
                }}
                onCancel={open}
                className="rounded-none shadow-none ring-0 lg:w-auto"
            />
        </div>
    )

    const dateToNow = (
        <DatePicker
            value={(rangeDateFrom ?? dayjs()).toDate()}
            showTime={dateToNowWithTime}
            showTimeToggle={allowTimePrecision}
            onIncludeTimeChange={setDateToNowWithTime}
            weekStartsOn={weekStartDay === 1 ? 1 : 0}
            onApply={(date) => {
                setRangeDateFrom(dayjs(date))
                setRangeDateTo(null)
                setExplicitDate(dateToNowWithTime)
                applyRange()
            }}
            onCancel={open}
            className="rounded-none shadow-none ring-0"
        />
    )

    return (
        <Popover open={isVisible} onOpenChange={(nextOpen) => (nextOpen ? open() : close())}>
            <PopoverTrigger
                render={
                    <Button
                        ref={ref}
                        id="daterange_selector"
                        variant="outline"
                        disabledReason={disabledReason}
                        data-attr="date-filter"
                        tooltip={formatResolvedDateRange(resolvedDateRange)}
                    />
                }
            >
                <IconCalendar />
                <span className="text-nowrap">{label}</span>
                <SelectTriggerIcon />
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto gap-0 p-0">
                {view === DateFilterView.FixedRange
                    ? fixedRange
                    : view === DateFilterView.DateToNow
                      ? dateToNow
                      : quickList}
            </PopoverContent>
        </Popover>
    )
})
