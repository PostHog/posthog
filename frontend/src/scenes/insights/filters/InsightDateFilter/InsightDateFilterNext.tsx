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
    Separator,
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

type InsightDateFilterNextProps = {
    disabled: boolean
}

export function InsightDateFilterNext({ disabled }: InsightDateFilterNextProps): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { querySource, dateRange, trendsFilter, isTrends } = useValues(insightVizDataLogic(insightProps))
    const { updateDateRange, updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { weekStartDay } = useValues(teamLogic)

    const [open, setOpen] = useState(false)
    const rollingMatch = ROLLING_DATE_FROM.exec(dateRange?.date_from ?? '')
    const [rollingCount, setRollingCount] = useState<number>(rollingMatch ? parseInt(rollingMatch[1]) : 30)
    const [rollingUnit, setRollingUnit] = useState<string>(rollingMatch?.[2] ?? 'd')

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
        updateDateRange({ date_from: `-${rollingCount}${rollingUnit}`, date_to: null }, true)
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
        <Popover open={open} onOpenChange={setOpen}>
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
                    className="shadow-none ring-0 rounded-b-none"
                />
                <Separator />
                <div className="flex items-center gap-2 px-3 py-2">
                    <span className="text-xs whitespace-nowrap">In the last</span>
                    <Input
                        type="number"
                        min={1}
                        value={rollingCount}
                        onChange={(e: ChangeEvent<HTMLInputElement>) =>
                            setRollingCount(Math.max(1, Number(e.target.value) || 1))
                        }
                        className="w-16"
                        aria-label="Rolling period count"
                        data-attr="insight-date-filter-next-rolling-count"
                    />
                    <Select
                        value={rollingUnit}
                        onValueChange={(unit: string | null) => setRollingUnit(unit ?? 'd')}
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
                    <>
                        <Separator />
                        <div className="flex items-center gap-2 px-3 py-2">
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
                    </>
                )}
                <Separator />
                <div className="flex items-center gap-2 px-3 py-2">
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
