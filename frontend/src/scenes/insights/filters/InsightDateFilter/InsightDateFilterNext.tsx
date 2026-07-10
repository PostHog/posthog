import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import {
    Button,
    CUSTOM_RANGE,
    DateTimePicker,
    Day,
    Label,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Switch,
    ToggleGroup,
    ToggleGroupItem,
    type DateTimeValue,
} from '@posthog/quill'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    ALL_DAY_NUMBERS,
    DAY_LABELS,
    DAY_LABELS_SINGLE,
    WEEKDAYS,
    WEEKENDS,
    computeDaysOfWeekUpdate,
    daysOfWeekLabel,
    getEffectiveDaysOfWeek,
} from './daysOfWeekFilterUtils'
import {
    ALL_TIME_PRESET,
    INSIGHT_DATE_PRESETS,
    dateRangeUpdateForPickerValue,
    insightDateLabel,
    insightDateRanges,
    pickerValueForDateRange,
    retentionDatePresets,
} from './insightDateFilterNextUtils'

const ROLLING_DATE_FROM = /^-(\d+)([hdwmy])$/

type InsightDateFilterNextProps = {
    disabled: boolean
}

export function InsightDateFilterNext({ disabled }: InsightDateFilterNextProps): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { querySource, dateRange, trendsFilter, retentionFilter, isTrends, isRetention } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateDateRange, updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { weekStartDay } = useValues(teamLogic)

    const [open, setOpen] = useState(false)
    const [customOpen, setCustomOpen] = useState(false)

    // Retention's range selects cohort-start buckets, so its presets scale with the period.
    const retentionPeriod = isRetention ? (retentionFilter?.period ?? 'Day') : null
    const presets = useMemo(
        () => [...(retentionPeriod ? retentionDatePresets(retentionPeriod) : INSIGHT_DATE_PRESETS), ALL_TIME_PRESET],
        [retentionPeriod]
    )

    const ranges = useMemo(() => insightDateRanges(weekStartDay, presets), [weekStartDay, presets])
    const pickerValue = useMemo(
        () => pickerValueForDateRange(dateRange?.date_from, dateRange?.date_to, ranges, undefined, presets),
        [dateRange?.date_from, dateRange?.date_to, ranges, presets]
    )

    const isRolling = ROLLING_DATE_FROM.test(dateRange?.date_from ?? '')
    const isCustom = pickerValue.range.id === CUSTOM_RANGE.id && !isRolling && !!dateRange?.date_from

    const handleOpenChange = (nextOpen: boolean): void => {
        if (nextOpen) {
            // Start on the preset list; jump straight to the calendar only if a custom range is active
            setCustomOpen(isCustom)
        }
        setOpen(nextOpen)
    }

    const selectedDays = getEffectiveDaysOfWeek(dateRange, trendsFilter)

    const labelParts = [insightDateLabel(dateRange?.date_from, dateRange?.date_to, presets)]
    if (isTrends && selectedDays.length > 0) {
        labelParts.push(daysOfWeekLabel(selectedDays))
    }
    if (dateRange?.excludeIncompletePeriods) {
        labelParts.push('Excl. incomplete')
    }

    const applyPicker = (next: DateTimeValue): void => {
        updateDateRange(dateRangeUpdateForPickerValue(next, presets), true)
        setOpen(false)
    }
    const setDays = (days: number[]): void => {
        updateQuerySource(computeDaysOfWeekUpdate(days, querySource, dateRange))
    }

    // Sits under the presets; reveals the calendar in place
    const railFooter = (
        <Button
            variant="default"
            size="default"
            left
            className="w-full justify-start"
            aria-selected={customOpen || isCustom}
            onClick={() => setCustomOpen(true)}
            data-attr="insight-date-filter-next-custom-range"
        >
            Custom range…
        </Button>
    )

    // Insight-only controls in the picker's footer slot — shown only in the narrow preset list.
    // The calendar view stays focused on range selection; these persist and are edited from the list.
    const showFooter = !customOpen && (isTrends || !isRetention)
    const pickerFooter = showFooter ? (
        <div className="flex flex-col gap-2 px-3 py-2">
            {isTrends && (
                <div className="flex flex-col gap-1">
                    <ToggleGroup
                        multiple
                        size="sm"
                        className="w-full max-w-60"
                        value={selectedDays.map(String)}
                        onValueChange={(days) => setDays(days.map(Number))}
                    >
                        {ALL_DAY_NUMBERS.map((day) => (
                            <ToggleGroupItem
                                key={day}
                                value={String(day)}
                                className="flex-1"
                                aria-label={DAY_LABELS[day]}
                                title={DAY_LABELS[day]}
                                data-attr={`insight-date-filter-next-day-${day}`}
                            >
                                {DAY_LABELS_SINGLE[day]}
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                    <div className="flex w-full max-w-60 items-center justify-center gap-2">
                        <Button variant="link" size="xs" onClick={() => setDays(WEEKDAYS)}>
                            Weekdays
                        </Button>
                        <Button variant="link" size="xs" onClick={() => setDays(WEEKENDS)}>
                            Weekends
                        </Button>
                        <Button variant="link" size="xs" onClick={() => setDays([])}>
                            All days
                        </Button>
                    </div>
                </div>
            )}
            {!isRetention && (
                <div className="flex items-center gap-2">
                    <Label htmlFor="insight-exclude-incomplete-period">Exclude incomplete period</Label>
                    <Switch
                        id="insight-exclude-incomplete-period"
                        size="sm"
                        checked={!!dateRange?.excludeIncompletePeriods}
                        onCheckedChange={(checked) =>
                            updateDateRange({ excludeIncompletePeriods: checked ? true : null }, true)
                        }
                        data-attr="insight-date-filter-next-exclude-incomplete"
                    />
                </div>
            )}
        </div>
    ) : undefined

    // data-lemon-skin opts these surfaces into the quill-as-lemon skin (lemon-skin.scss) so the
    // filter sits next to Lemon chrome without a visual jump. The skin matches the attribute on the
    // element itself or an ancestor, so the trigger carries it directly; portaled content
    // (popover/select) carries it too since it renders outside this subtree.
    return (
        <Popover open={open} onOpenChange={handleOpenChange}>
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        size="default"
                        data-attr="insight-date-filter-next"
                        data-quill
                        data-lemon-skin
                        disabled={disabled || !!editingDisabledReason}
                        title={editingDisabledReason ?? undefined}
                    >
                        <IconCalendar />
                        {labelParts.join(' · ')}
                    </Button>
                }
            />
            <PopoverContent data-lemon-skin align="start" className="w-auto p-0 overflow-hidden">
                <DateTimePicker
                    value={pickerValue}
                    ranges={ranges}
                    applyOnRangeSelect
                    rangesFooter={railFooter}
                    footer={pickerFooter}
                    showCalendar={customOpen}
                    showHeader={false}
                    showTime={false}
                    weekStartsOn={weekStartDay === 1 ? Day.MONDAY : Day.SUNDAY}
                    onApply={applyPicker}
                    onCancel={() => setCustomOpen(false)}
                    className="shadow-none ring-0 rounded-none"
                />
            </PopoverContent>
        </Popover>
    )
}
