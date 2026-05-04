import type { Meta, StoryObj } from '@storybook/react'
import { format, subDays } from 'date-fns'
import { Clock } from 'lucide-react'
import * as React from 'react'

import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill-primitives'

import { CUSTOM_RANGE } from './date-time-ranges'
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
