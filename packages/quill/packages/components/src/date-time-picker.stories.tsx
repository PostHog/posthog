import type { Meta, StoryObj } from '@storybook/react'
import {
    endOfMonth,
    endOfQuarter,
    format,
    startOfMonth,
    startOfQuarter,
    startOfYear,
    subDays,
    subMonths,
    subQuarters,
} from 'date-fns'
import { Clock } from 'lucide-react'
import * as React from 'react'

import { Button, Label, Popover, PopoverContent, PopoverTrigger, Separator, Switch, ToggleGroup, ToggleGroupItem } from '@posthog/quill-primitives'

import { CUSTOM_RANGE, type DateTimeRange } from './date-time-ranges'
import { DateTimePicker, type DateTimeValue } from './date-time-picker'
import { quickRanges } from './date-time-ranges'
import { Day } from './use-calendar'

function formatTriggerLabel(value: DateTimeValue): string {
    if (value.range.id !== CUSTOM_RANGE.id) {
        return value.range.name
    }
    const startStr = format(value.start, 'MMM do HH:mm')
    const diffMs = Math.abs(new Date().getTime() - value.end.getTime())
    const endStr = diffMs < 60_000 ? 'now' : format(value.end, 'MMM do HH:mm')
    return `${startStr} to ${endStr}`
}

const meta = {
    title: 'Components/DateTimePicker',
    component: DateTimePicker,
    tags: ['autodocs'],
} satisfies Meta<typeof DateTimePicker>

export default meta
type Story = StoryObj<typeof meta>

const initialValue: DateTimeValue = {
    start: subDays(new Date(), 7),
    end: new Date(),
    range: quickRanges.find((r) => r.name === 'Last 7 days')!,
}

const baseArgs = {
    value: initialValue,
    onApply: () => undefined,
}

export const Default: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        return <DateTimePicker value={value} onApply={setValue} />
    },
}

export const THIS_COMPONENT_IS_EXPERIMENTAL: Story = {
    args: baseArgs,
    render: () => {
        return <>Just a small note this is experimental and likely not ready for use.</>
    },
}

export const InPopover: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        const [open, setOpen] = React.useState(false)
        return (
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger
                    render={
                        <Button variant="outline" size="sm">
                            <Clock />
                            {formatTriggerLabel(value)}
                        </Button>
                    }
                />
                <PopoverContent align="start" className="w-auto p-0">
                    <DateTimePicker
                        value={value}
                        onApply={(next) => {
                            setValue(next)
                            setOpen(false)
                        }}
                        onCancel={() => setOpen(false)}
                    />
                </PopoverContent>
            </Popover>
        )
    },
}

export const CustomMaxDate: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>({
            start: subDays(new Date(), 14),
            end: subDays(new Date(), 7),
            range: quickRanges[0],
        })
        return <DateTimePicker value={value} onApply={setValue} maxDate={subDays(new Date(), 1)} />
    },
}

export const CustomMinDate: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        return <DateTimePicker value={value} onApply={setValue} minDate={subDays(new Date(), 2)} />
    },
}

export const MinDateAndMaxDate: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        return (
            <DateTimePicker
                value={value}
                onApply={setValue}
                minDate={subDays(new Date(), 30)}
                maxDate={subDays(new Date(), 1)}
            />
        )
    },
}

export const EuropeanDateFormat: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        return <DateTimePicker value={value} onApply={setValue} dateFormat="DMY" />
    },
}

export const ISODateFormat: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        return <DateTimePicker value={value} onApply={setValue} dateFormat="YMD" />
    },
}

export const WithSettingsLink: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        return (
            <DateTimePicker
                value={value}
                onApply={setValue}
                onDateTimeSettings={() => alert('Open date & time settings')}
            />
        )
    },
}

const calendarRanges: DateTimeRange[] = [
    { id: 1, name: 'This month', rangeSetter: (d) => startOfMonth(d) },
    { id: 2, name: 'Last month', rangeSetter: (d) => startOfMonth(subMonths(d, 1)), endSetter: (d) => endOfMonth(subMonths(d, 1)) },
    { id: 3, name: 'This quarter', rangeSetter: (d) => startOfQuarter(d) },
    { id: 4, name: 'Last quarter', rangeSetter: (d) => startOfQuarter(subQuarters(d, 1)), endSetter: (d) => endOfQuarter(subQuarters(d, 1)) },
    { id: 5, name: 'Year to date', rangeSetter: (d) => startOfYear(d) },
]

export const CustomRanges: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>({
            start: startOfMonth(new Date()),
            end: new Date(),
            range: calendarRanges[0],
        })
        return <DateTimePicker value={value} onApply={setValue} ranges={calendarRanges} />
    },
}

export const EmbeddedDayGranular: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>({
            start: startOfMonth(new Date()),
            end: new Date(),
            range: calendarRanges[0],
        })
        return (
            <DateTimePicker
                value={value}
                onApply={setValue}
                ranges={calendarRanges}
                showHeader={false}
                showTime={false}
                className="shadow-none ring-1"
            />
        )
    },
}

export const WeekStartsThursday: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        return <DateTimePicker value={value} onApply={setValue} weekStartsOn={Day.THURSDAY} />
    },
}

export const NarrowContainer: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        return <DateTimePicker value={value} onApply={setValue} compact />
    },
}

const analyticsRanges: DateTimeRange[] = [
    { id: 1, name: 'Today', rangeSetter: (d) => d },
    { id: 2, name: 'Last 7 days', rangeSetter: (d) => subDays(d, 7) },
    { id: 3, name: 'Last 30 days', rangeSetter: (d) => subDays(d, 30) },
    { id: 4, name: 'Last 90 days', rangeSetter: (d) => subDays(d, 90) },
    { id: 5, name: 'This month', rangeSetter: (d) => startOfMonth(d) },
    { id: 6, name: 'Last month', rangeSetter: (d) => startOfMonth(subMonths(d, 1)), endSetter: (d) => endOfMonth(subMonths(d, 1)) },
    { id: 7, name: 'Year to date', rangeSetter: (d) => startOfYear(d) },
]

// An exclusions control for the footerExtra slot: a small link opening a panel with an
// incomplete-period toggle and exclude-day chips. Host-supplied; the picker only provides the slot.
function ExcludeControlDemo(): React.ReactElement {
    const [excludedDays, setExcludedDays] = React.useState<string[]>([])
    const [excludeIncomplete, setExcludeIncomplete] = React.useState(false)
    const [openPanel, setOpenPanel] = React.useState(false)
    const rootRef = React.useRef<HTMLDivElement>(null)
    React.useEffect(() => {
        if (!openPanel) {
            return
        }
        const onPointerDown = (event: PointerEvent): void => {
            if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
                setOpenPanel(false)
            }
        }
        document.addEventListener('pointerdown', onPointerDown)
        return () => document.removeEventListener('pointerdown', onPointerDown)
    }, [openPanel])
    const labels: Record<string, string> = { 1: 'M', 2: 'T', 3: 'W', 4: 'T', 5: 'F', 6: 'S', 7: 'S' }
    const sorted = [...excludedDays].sort().join(',')
    const parts: string[] = []
    if (excludedDays.length > 0) {
        parts.push(sorted === '6,7' ? 'weekends' : sorted === '1,2,3,4,5' ? 'weekdays' : `${excludedDays.length} days`)
    }
    if (excludeIncomplete) {
        parts.push('incomplete')
    }
    return (
        <div className="relative" ref={rootRef}>
            <Button variant="link" size="xs" aria-expanded={openPanel} onClick={() => setOpenPanel((prev) => !prev)}>
                {parts.length > 0 ? `Excluding ${parts.join(', ')}` : '+ Exclude'}
            </Button>
            {openPanel && (
                <div className="bg-card absolute bottom-full left-0 z-10 mb-1 flex w-64 flex-col rounded-md border shadow-md">
                    <div className="flex items-center justify-between gap-2 px-3 py-2.5">
                        <Label htmlFor="story-exclude-incomplete">Incomplete period</Label>
                        <Switch
                            id="story-exclude-incomplete"
                            size="sm"
                            checked={excludeIncomplete}
                            onCheckedChange={setExcludeIncomplete}
                        />
                    </div>
                    <Separator />
                    <div className="flex flex-col gap-2 px-3 py-2.5">
                        <ToggleGroup
                            multiple
                            size="sm"
                            className="w-full"
                            value={excludedDays}
                            onValueChange={setExcludedDays}
                        >
                            {Object.keys(labels).map((day) => (
                                <ToggleGroupItem key={day} value={day} className="flex-1">
                                    {labels[day]}
                                </ToggleGroupItem>
                            ))}
                        </ToggleGroup>
                        <div className="flex items-center justify-center gap-3">
                            <Button variant="link" size="xs" onClick={() => setExcludedDays(['6', '7'])}>
                                Weekends
                            </Button>
                            <Button variant="link" size="xs" onClick={() => setExcludedDays(['1', '2', '3', '4', '5'])}>
                                Weekdays
                            </Button>
                            <Button variant="link" size="xs" onClick={() => setExcludedDays([])}>
                                Clear
                            </Button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export const PresetsFirst: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>({
            start: subDays(new Date(), 7),
            end: new Date(),
            range: analyticsRanges.find((r) => r.name === 'Last 7 days')!,
        })
        return <DateTimePicker value={value} onApply={setValue} ranges={analyticsRanges} presetsFirst showTime={false} />
    },
}

export const PresetsFirstWithExclusions: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>({
            start: subDays(new Date(), 7),
            end: new Date(),
            range: analyticsRanges.find((r) => r.name === 'Last 7 days')!,
        })
        return (
            <DateTimePicker
                value={value}
                onApply={setValue}
                ranges={analyticsRanges}
                presetsFirst
                showTime={false}
                footerExtra={<ExcludeControlDemo />}
            />
        )
    },
}

export const PresetsFirstInPopover: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>({
            start: subDays(new Date(), 7),
            end: new Date(),
            range: analyticsRanges.find((r) => r.name === 'Last 7 days')!,
        })
        const [open, setOpen] = React.useState(false)
        return (
            <div className="h-120">
                <Popover open={open} onOpenChange={setOpen}>
                    <PopoverTrigger render={<Button variant="outline">{formatTriggerLabel(value)}</Button>} />
                    <PopoverContent
                        align="start"
                        collisionAvoidance={{ align: 'none' }}
                        className="w-auto overflow-hidden border-none p-0 shadow-none ring-0"
                    >
                        <DateTimePicker
                            value={value}
                            onApply={(next) => {
                                setValue(next)
                                setOpen(false)
                            }}
                            ranges={analyticsRanges}
                            presetsFirst
                            showTime={false}
                            footerExtra={<ExcludeControlDemo />}
                        />
                    </PopoverContent>
                </Popover>
            </div>
        )
    },
}
