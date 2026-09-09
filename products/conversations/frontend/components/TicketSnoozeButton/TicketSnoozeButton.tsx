import { useValues } from 'kea'
import { useState } from 'react'

import { IconX } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { Button, ButtonGroup, DatePicker, Popover, PopoverContent, PopoverTrigger } from 'lib/ui/quill'
import { teamLogic } from 'scenes/teamLogic'

interface TicketSnoozeButtonProps {
    snoozedUntil: string | null
    onChange: (snoozedUntil: string | null) => void
    onApplyAndSetOnHold: (snoozedUntil: string) => void
    disabledReason?: string
}

function toIsoMinute(date: Date): string {
    const next = dayjs(date).startOf('minute')
    return (next.isBefore(dayjs()) ? dayjs().startOf('minute') : next).toISOString()
}

export function TicketSnoozeButton({
    snoozedUntil,
    onChange,
    onApplyAndSetOnHold,
    disabledReason,
}: TicketSnoozeButtonProps): JSX.Element {
    const { weekStartDay } = useValues(teamLogic)
    const [open, setOpen] = useState(false)

    const pickerValue = snoozedUntil ? dayjs(snoozedUntil).toDate() : dayjs().add(1, 'hour').toDate()
    const triggerLabel = snoozedUntil ? dayjs(snoozedUntil).format('MMMM D, YYYY h:mm A') : 'Not snoozed'

    if (disabledReason) {
        return (
            <Button variant="outline" size="sm" disabled title={disabledReason} aria-label={triggerLabel}>
                <span className="text-nowrap">{triggerLabel}</span>
            </Button>
        )
    }

    const picker = (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger render={<Button variant="outline" size="sm" aria-label={triggerLabel} />}>
                <span className="text-nowrap">{triggerLabel}</span>
            </PopoverTrigger>
            <PopoverContent
                align="end"
                collisionAvoidance={{ side: 'flip', align: 'shift', fallbackAxisSide: 'none' }}
                className="w-auto overflow-hidden border-none p-0 shadow-none ring-0"
            >
                <DatePicker
                    key={snoozedUntil ?? 'empty'}
                    value={pickerValue}
                    minDate={dayjs().startOf('day').toDate()}
                    maxDate={dayjs().add(10, 'year').toDate()}
                    showTime
                    showTimeToggle={false}
                    weekStartsOn={weekStartDay === 1 ? 1 : 0}
                    onCancel={() => setOpen(false)}
                    onApply={(date) => {
                        onChange(toIsoMinute(date))
                        setOpen(false)
                    }}
                    extraActions={[
                        {
                            label: 'Apply and set to on hold',
                            onClick: (date) => {
                                onApplyAndSetOnHold(toIsoMinute(date))
                                setOpen(false)
                            },
                        },
                    ]}
                />
            </PopoverContent>
        </Popover>
    )

    if (!snoozedUntil) {
        return picker
    }

    return (
        <ButtonGroup>
            {picker}
            <Button
                variant="outline"
                size="icon-sm"
                aria-label="Clear date"
                title="Clear date"
                onClick={() => onChange(null)}
            >
                <IconX />
            </Button>
        </ButtonGroup>
    )
}
