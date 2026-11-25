import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import {
    Button,
    CUSTOM_RANGE,
    DateTimePicker,
    type DateTimeRange,
    type DateTimeValue,
    Popover,
    PopoverContent,
    PopoverTrigger,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import {
    MODELS_USAGE_RANGE_DAYS,
    lastCompleteUsageDay,
    modelsUsageRangeLabel,
    modelsUsageRelativeDateFrom,
} from './modelsUsageDateRanges'
import { modelsUsageLogic } from './modelsUsageLogic'

const DATE_FORMAT = 'YYYY-MM-DD'

interface UsageRange extends DateTimeRange {
    relativeDateFrom: string
}

const USAGE_RANGES: UsageRange[] = MODELS_USAGE_RANGE_DAYS.map((days) => ({
    id: days,
    name: modelsUsageRangeLabel(days),
    relativeDateFrom: modelsUsageRelativeDateFrom(days),
    rangeSetter: () =>
        dayjs(lastCompleteUsageDay())
            .subtract(days - 1, 'day')
            .toDate(),
    endSetter: () => lastCompleteUsageDay(),
}))

function toPickerValue(dateFrom: string, dateTo: string | null): DateTimeValue {
    const now = new Date()
    const preset = dateTo === null ? USAGE_RANGES.find((range) => range.relativeDateFrom === dateFrom) : undefined
    if (preset) {
        return { start: preset.rangeSetter(now), end: preset.endSetter?.(now) ?? now, range: preset }
    }
    return {
        start: dayjs(dateFrom).toDate(),
        end: dateTo ? dayjs(dateTo).toDate() : lastCompleteUsageDay(),
        range: CUSTOM_RANGE,
    }
}

function triggerLabel(value: DateTimeValue): string {
    if (value.range.id !== CUSTOM_RANGE.id) {
        return value.range.name
    }
    return `${dayjs(value.start).format('MMM D, YYYY')} – ${dayjs(value.end).format('MMM D, YYYY')}`
}

export function QuillModelsUsageDateFilter(): JSX.Element {
    const { dateFrom, dateTo, usageLoading, jobsLoading } = useValues(modelsUsageLogic)
    const { setDateRange } = useActions(modelsUsageLogic)
    const [open, setOpen] = useState(false)
    const value = toPickerValue(dateFrom, dateTo)

    const apply = (next: DateTimeValue): void => {
        const preset = USAGE_RANGES.find((range) => range.id === next.range.id)
        if (preset) {
            setDateRange(preset.relativeDateFrom, null)
        } else {
            setDateRange(dayjs(next.start).format(DATE_FORMAT), dayjs(next.end).format(DATE_FORMAT))
        }
        setOpen(false)
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        disabledReason={usageLoading || jobsLoading ? 'Usage is loading' : undefined}
                        data-attr="models-usage-date-range"
                    />
                }
            >
                <IconCalendar />
                {triggerLabel(value)}
            </PopoverTrigger>
            <PopoverContent align="end" className="w-auto p-0">
                <DateTimePicker
                    value={value}
                    onApply={apply}
                    onCancel={() => setOpen(false)}
                    ranges={USAGE_RANGES}
                    maxDate={lastCompleteUsageDay()}
                    showTime={false}
                />
            </PopoverContent>
        </Popover>
    )
}
