import { useActions, useValues } from 'kea'
import { type ChangeEvent, useMemo, useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import {
    Button,
    DateTimePicker,
    Day,
    Input,
    Label,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
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
    WEEKDAYS,
    computeDaysOfWeekUpdate,
    daysOfWeekLabel,
    getEffectiveDaysOfWeek,
} from './daysOfWeekFilterUtils'
import {
    dateRangeUpdateForPickerValue,
    insightDateLabel,
    insightDateRanges,
    pickerValueForDateRange,
} from './insightDateFilterNextUtils'

const ROLLING_UNITS: Record<string, string> = {
    h: 'hours',
    d: 'days',
    w: 'weeks',
    m: 'months',
    y: 'years',
}

const ROLLING_DATE_FROM = /^-(\d+)([hdwmy])$/
const DEFAULT_ROLLING_COUNT = '30'
const DEFAULT_ROLLING_UNIT = 'd'

type InsightDateFilterNextProps = {
    disabled: boolean
}

export function InsightDateFilterNext({ disabled }: InsightDateFilterNextProps): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { querySource, dateRange, trendsFilter, isTrends } = useValues(insightVizDataLogic(insightProps))
    const { updateDateRange, updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { weekStartDay } = useValues(teamLogic)

    const [open, setOpen] = useState(false)
    const [rollingCount, setRollingCount] = useState<string>(DEFAULT_ROLLING_COUNT)
    const [rollingUnit, setRollingUnit] = useState<string>(DEFAULT_ROLLING_UNIT)

    const handleOpenChange = (nextOpen: boolean): void => {
        if (nextOpen) {
            const rollingMatch = ROLLING_DATE_FROM.exec(dateRange?.date_from ?? '')
            setRollingCount(rollingMatch?.[1] ?? DEFAULT_ROLLING_COUNT)
            setRollingUnit(rollingMatch?.[2] ?? DEFAULT_ROLLING_UNIT)
        }
        setOpen(nextOpen)
    }

    const ranges = useMemo(() => insightDateRanges(weekStartDay), [weekStartDay])
    const pickerValue = useMemo(
        () => pickerValueForDateRange(dateRange?.date_from, dateRange?.date_to, ranges),
        [dateRange?.date_from, dateRange?.date_to, ranges]
    )

    const selectedDays = getEffectiveDaysOfWeek(dateRange, trendsFilter)

    const labelParts = [insightDateLabel(dateRange?.date_from, dateRange?.date_to)]
    if (isTrends && selectedDays.length > 0) {
        labelParts.push(daysOfWeekLabel(selectedDays))
    }
    if (dateRange?.excludeIncompletePeriods) {
        labelParts.push('Excl. incomplete')
    }

    const applyPicker = (next: DateTimeValue): void => {
        updateDateRange(dateRangeUpdateForPickerValue(next), true)
        setOpen(false)
    }
    const applyRolling = (): void => {
        const count = Math.max(1, parseInt(rollingCount) || 1)
        updateDateRange({ date_from: `-${count}${rollingUnit}`, date_to: null }, true)
        setOpen(false)
    }
    const applyAllTime = (): void => {
        updateDateRange({ date_from: 'all', date_to: null }, true)
        setOpen(false)
    }
    const setDays = (days: number[]): void => {
        updateQuerySource(computeDaysOfWeekUpdate(days, querySource, dateRange))
    }

    return (
        <Popover open={open} onOpenChange={handleOpenChange}>
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        size="sm"
                        data-attr="insight-date-filter-next"
                        data-quill
                        disabled={disabled || !!editingDisabledReason}
                        title={editingDisabledReason ?? undefined}
                    >
                        <IconCalendar />
                        {labelParts.join(' · ')}
                    </Button>
                }
            />
            <PopoverContent align="start" className="w-auto p-0 overflow-hidden">
                <DateTimePicker
                    value={pickerValue}
                    ranges={ranges}
                    weekStartsOn={weekStartDay === 1 ? Day.MONDAY : Day.SUNDAY}
                    onApply={applyPicker}
                    onCancel={() => setOpen(false)}
                    showHeader={false}
                    showTime={false}
                    className="shadow-none ring-0 rounded-b-none"
                />
                {/* Extra sections continue the picker footer's muted band so the popover reads as one surface */}
                <div className="flex items-center gap-2 border-t border-border bg-muted/30 px-3 py-1.5">
                    <span className="text-xs whitespace-nowrap text-muted-foreground">In the last</span>
                    <Input
                        type="number"
                        min={1}
                        value={rollingCount}
                        onChange={(e: ChangeEvent<HTMLInputElement>) =>
                            setRollingCount(e.target.value.replace(/[^0-9]/g, ''))
                        }
                        className="w-14"
                        aria-label="Rolling period count"
                        data-attr="insight-date-filter-next-rolling-count"
                    />
                    <Select
                        value={rollingUnit}
                        onValueChange={(unit: string | null) => setRollingUnit(unit ?? DEFAULT_ROLLING_UNIT)}
                        items={ROLLING_UNITS}
                    >
                        <SelectTrigger size="sm" aria-label="Rolling period unit">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {Object.entries(ROLLING_UNITS).map(([value, label]) => (
                                <SelectItem key={value} value={value}>
                                    {label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                    <Button size="sm" onClick={applyRolling} data-attr="insight-date-filter-next-rolling-apply">
                        Apply
                    </Button>
                    <Button
                        variant="link"
                        size="sm"
                        className="ml-auto"
                        onClick={applyAllTime}
                        data-attr="insight-date-filter-next-all-time"
                    >
                        All time
                    </Button>
                </div>
                {isTrends && (
                    <div className="flex items-center gap-2 border-t border-border bg-muted/30 px-3 py-1.5">
                        <ToggleGroup
                            multiple
                            size="sm"
                            value={selectedDays.map(String)}
                            onValueChange={(days) => setDays(days.map(Number))}
                        >
                            {ALL_DAY_NUMBERS.map((day) => (
                                <ToggleGroupItem
                                    key={day}
                                    value={String(day)}
                                    aria-label={DAY_LABELS[day]}
                                    data-attr={`insight-date-filter-next-day-${day}`}
                                >
                                    {DAY_LABELS[day]}
                                </ToggleGroupItem>
                            ))}
                        </ToggleGroup>
                        <Button variant="link" size="sm" onClick={() => setDays(WEEKDAYS)}>
                            Weekdays
                        </Button>
                        <Button variant="link" size="sm" onClick={() => setDays([])}>
                            All days
                        </Button>
                    </div>
                )}
                <div className="flex items-center gap-2 border-t border-border bg-muted/30 px-3 py-1.5">
                    <Switch
                        id="insight-exclude-incomplete-period"
                        size="sm"
                        checked={!!dateRange?.excludeIncompletePeriods}
                        onCheckedChange={(checked) =>
                            updateDateRange({ excludeIncompletePeriods: checked ? true : null }, true)
                        }
                        data-attr="insight-date-filter-next-exclude-incomplete"
                    />
                    <Label htmlFor="insight-exclude-incomplete-period">Exclude incomplete period</Label>
                </div>
            </PopoverContent>
        </Popover>
    )
}
