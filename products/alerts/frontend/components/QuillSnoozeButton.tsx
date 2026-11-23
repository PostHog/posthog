import { useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import {
    Button,
    DatePicker,
    ItemMenuItem,
    ItemSeparator,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Text,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { formatDate } from 'lib/utils/datetime'

const DATETIME_FORMAT = 'MMM D - HH:mm'
const MAX_SNOOZE_DAYS = 31

const SNOOZE_PRESETS: { label: string; value: string; minutes: number }[] = [
    { label: '30 minutes', value: '+30m', minutes: 30 },
    { label: '1 hour', value: '+1h', minutes: 60 },
    { label: '4 hours', value: '+4h', minutes: 4 * 60 },
    { label: '24 hours', value: '+24h', minutes: 24 * 60 },
]

interface QuillSnoozeButtonProps {
    onChange: (snoozeUntil: string) => void
    onClear?: () => void
    value?: string
    disabledReason?: string
}

function focusSiblingMenuItem(event: React.KeyboardEvent<HTMLDivElement>): void {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') {
        return
    }

    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'))
    const current = items.indexOf(document.activeElement as HTMLElement)
    const next = event.key === 'ArrowDown' ? current + 1 : current - 1

    items[(next + items.length) % items.length]?.focus()
    event.preventDefault()
}

export function QuillSnoozeButton({ onChange, onClear, value, disabledReason }: QuillSnoozeButtonProps): JSX.Element {
    const [open, setOpen] = useState(false)

    if (disabledReason) {
        return (
            <Button variant="outline" disabledReason={disabledReason}>
                <IconCalendar />
                Snooze until
            </Button>
        )
    }

    const now = dayjs()

    const snooze = (snoozeUntil: string): void => {
        onChange(snoozeUntil)
        setOpen(false)
    }

    const clear = (): void => {
        onClear?.()
        setOpen(false)
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            {value ? (
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    Snoozed until
                </Text>
            ) : null}
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger
                    render={
                        <Button variant="outline">
                            <IconCalendar />
                            {value ? formatDate(dayjs(value), DATETIME_FORMAT) : 'Snooze until'}
                        </Button>
                    }
                />
                <PopoverContent align="start" className="w-auto p-0">
                    <div className="flex flex-wrap">
                        <div
                            className="flex min-w-48 flex-col gap-0.5 p-1"
                            role="menu"
                            aria-label="Snooze for"
                            onKeyDown={focusSiblingMenuItem}
                        >
                            {SNOOZE_PRESETS.map((preset) => (
                                <ItemMenuItem key={preset.value} onClick={() => snooze(preset.value)}>
                                    <span>{preset.label}</span>
                                    <span className="ml-auto pl-4 text-muted-foreground tabular-nums">
                                        {formatDate(now.add(preset.minutes, 'minute'), DATETIME_FORMAT)}
                                    </span>
                                </ItemMenuItem>
                            ))}
                            {onClear && value ? (
                                <>
                                    <ItemSeparator className="my-1" />
                                    <ItemMenuItem className="text-destructive-foreground" onClick={clear}>
                                        Clear snooze
                                    </ItemMenuItem>
                                </>
                            ) : null}
                        </div>
                        <DatePicker
                            value={value ? dayjs(value).toDate() : now.add(1, 'hour').toDate()}
                            minDate={now.toDate()}
                            maxDate={now.add(MAX_SNOOZE_DAYS, 'day').toDate()}
                            showTime
                            showTimeToggle={false}
                            onApply={(date) => snooze(dayjs(date).toISOString())}
                            onCancel={() => setOpen(false)}
                            className="rounded-none border-l border-border shadow-none ring-0"
                        />
                    </div>
                </PopoverContent>
            </Popover>
        </div>
    )
}
