import { useMergeRefs } from '@floating-ui/react'
import { useActions, useValues } from 'kea'
import { forwardRef, useEffect, useRef, useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import {
    Button,
    CUSTOM_RANGE,
    DatePicker,
    DateTimePicker,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuList,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Popover,
    PopoverContent,
    ScrollArea,
    SelectTriggerIcon,
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

const ROLLING_VALUE = 'rolling'
const DATE_TO_NOW_VALUE = 'date-to-now'
const FIXED_RANGE_VALUE = 'fixed-range'

// A menu treats typed keys as item navigation, which would steal them from the rolling range input
function keepKeysInField(event: React.KeyboardEvent): void {
    if (event.key !== 'Escape') {
        event.stopPropagation()
    }
}

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
    const triggerRef = useRef<HTMLButtonElement>(null)
    const mergedTriggerRef = useMergeRefs([ref, triggerRef])

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
    const weekStartsOn = weekStartDay === 1 ? 1 : 0

    const visibleOptions = dateOptions.filter(
        ({ key: optionKey, inactive }) =>
            !(optionKey === CUSTOM_OPTION_KEY && !showCustom) && !(inactive && label !== optionKey)
    )
    const activeOption = visibleOptions.find(
        ({ values }) => (dateFrom ?? null) === (values[0] ?? null) && (dateTo ?? null) === (values[1] ?? null)
    )
    const selectedValue =
        activeOption?.key ??
        (isFixedRange ? FIXED_RANGE_VALUE : isDateToNow ? DATE_TO_NOW_VALUE : isRollingDateRange ? ROLLING_VALUE : '')

    const calendarView = isVisible && (view === DateFilterView.FixedRange || view === DateFilterView.DateToNow)

    return (
        <>
            <DropdownMenu
                // The unit select and exclusions flyout open their own popups, which a modal menu would block
                modal={false}
                open={isVisible && view === DateFilterView.QuickList}
                onOpenChange={(nextOpen) => (nextOpen ? open() : close())}
            >
                <DropdownMenuTrigger
                    render={
                        <Button
                            ref={mergedTriggerRef}
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
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                    <DropdownMenuList>
                        <DropdownMenuRadioGroup value={selectedValue}>
                            <ScrollArea
                                hideScrollbars
                                scrollShadows={false}
                                viewportClassName="max-h-80 scroll-mask-y-4 scroll-py-4"
                            >
                                {visibleOptions.map(({ key: optionKey, values }) => (
                                    <DropdownMenuRadioItem
                                        key={optionKey}
                                        value={optionKey}
                                        // pinned: data-attr values feed autocapture dashboards and tests
                                        data-attr={`date-filter-${optionKey.toLowerCase().replace(/\s+/g, '-')}`}
                                        onClick={() =>
                                            setDate(values[0] || null, values[1] || null, false, explicitDate)
                                        }
                                        tooltip={makeLabel?.(
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
                                                ? dateFilterToText(
                                                      values[1],
                                                      undefined,
                                                      '',
                                                      [],
                                                      false,
                                                      'MMMM D, YYYY',
                                                      true
                                                  )
                                                : undefined
                                        )}
                                    >
                                        {optionKey === CUSTOM_OPTION_KEY ? NO_OVERRIDE_RANGE_PLACEHOLDER : optionKey}
                                    </DropdownMenuRadioItem>
                                ))}
                                <div className="flex items-center gap-1">
                                    <DropdownMenuRadioItem
                                        value={ROLLING_VALUE}
                                        className="w-auto shrink-0"
                                        data-attr="rolling-date-range-filter"
                                        onClick={select}
                                        tooltip={makeLabel?.(formattedDate, startOfDateRange)}
                                    >
                                        In the last
                                    </DropdownMenuRadioItem>
                                    <div onKeyDown={keepKeysInField}>
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
                            </ScrollArea>
                            <DropdownMenuSeparator />
                            <DropdownMenuRadioItem value={DATE_TO_NOW_VALUE} onClick={openDateToNow}>
                                From custom date until now…
                            </DropdownMenuRadioItem>
                            <DropdownMenuRadioItem value={FIXED_RANGE_VALUE} onClick={openFixedRange}>
                                Custom fixed date range…
                            </DropdownMenuRadioItem>
                        </DropdownMenuRadioGroup>
                    </DropdownMenuList>
                    {(showExplicitDateToggle || showExclusions) && (
                        <>
                            <DropdownMenuSeparator />
                            <div className="flex flex-col gap-1">
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
                </DropdownMenuContent>
            </DropdownMenu>
            <Popover open={calendarView} onOpenChange={(nextOpen) => !nextOpen && close()}>
                <PopoverContent anchor={triggerRef} align="start" className="w-auto gap-0 p-0">
                    {view === DateFilterView.FixedRange ? (
                        <div className="flex flex-col">
                            {showFixedRangeTimeToggle && (
                                <div className="border-b border-border px-3 py-1.5">
                                    <QuillChartOptionSwitch
                                        label="Include time"
                                        checked={fixedRangeWithTime}
                                        onChange={(includeTime) =>
                                            setFixedRangeGranularity(includeTime ? 'minute' : 'day')
                                        }
                                    />
                                </div>
                            )}
                            <DateTimePicker
                                // The picker reads `value` at mount only, so remount it when time is switched on or off
                                key={fixedRangeWithTime ? 'time' : 'day'}
                                ranges={[]}
                                showHeader={false}
                                showTime={fixedRangeWithTime}
                                weekStartsOn={weekStartsOn}
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
                    ) : (
                        <DatePicker
                            value={(rangeDateFrom ?? dayjs()).toDate()}
                            showTime={dateToNowWithTime}
                            showTimeToggle={allowTimePrecision}
                            onIncludeTimeChange={setDateToNowWithTime}
                            weekStartsOn={weekStartsOn}
                            onApply={(date) => {
                                setRangeDateFrom(dayjs(date))
                                setRangeDateTo(null)
                                setExplicitDate(dateToNowWithTime)
                                applyRange()
                            }}
                            onCancel={open}
                            className="rounded-none shadow-none ring-0"
                        />
                    )}
                </PopoverContent>
            </Popover>
        </>
    )
})
