import { useEffect, useId, useRef, useState } from 'react'

import { Button, Label, Separator, Switch, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

const DAY_LABELS_SINGLE: Record<number, string> = { 1: 'M', 2: 'T', 3: 'W', 4: 'T', 5: 'F', 6: 'S', 7: 'S' }
const DAY_LABELS: Record<number, string> = { 1: 'Mon', 2: 'Tue', 3: 'Wed', 4: 'Thu', 5: 'Fri', 6: 'Sat', 7: 'Sun' }
const WEEKDAYS = [1, 2, 3, 4, 5]
const WEEKENDS = [6, 7]

export interface DateExclusionsControlProps {
    /** ISO days (1=Mon…7=Sun) excluded from the range; omit to hide the days section. */
    excludedDays?: number[]
    onExcludedDaysChange?: (days: number[]) => void
    /** Omit to hide the incomplete-period row. */
    excludeIncomplete?: boolean
    onExcludeIncompleteChange?: (checked: boolean) => void
}

function excludedDaysSummary(days: number[]): string {
    const sorted = [...days].sort((a, b) => a - b)
    if (sorted.length === WEEKENDS.length && WEEKENDS.every((day) => sorted.includes(day))) {
        return 'weekends'
    }
    if (sorted.length === WEEKDAYS.length && WEEKDAYS.every((day) => sorted.includes(day))) {
        return 'weekdays'
    }
    return sorted.length <= 2 ? sorted.map((day) => DAY_LABELS[day]).join(', ') : `${sorted.length} days`
}

/** "+ Exclude" link opening a panel with an incomplete-period toggle and exclude-day chips.
 *  Made for the date filter's `footerExtra` slot; the panel opens upward from the actions bar. */
export function DateExclusionsControl({
    excludedDays,
    onExcludedDaysChange,
    excludeIncomplete,
    onExcludeIncompleteChange,
}: DateExclusionsControlProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const rootRef = useRef<HTMLDivElement>(null)
    const incompleteId = useId()

    useEffect(() => {
        if (!open) {
            return
        }
        const onPointerDown = (event: PointerEvent): void => {
            if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
                setOpen(false)
            }
        }
        document.addEventListener('pointerdown', onPointerDown)
        return () => document.removeEventListener('pointerdown', onPointerDown)
    }, [open])

    const showDays = excludedDays !== undefined && onExcludedDaysChange !== undefined
    const showIncomplete = excludeIncomplete !== undefined && onExcludeIncompleteChange !== undefined

    const parts: string[] = []
    if (showDays && excludedDays.length > 0) {
        parts.push(excludedDaysSummary(excludedDays))
    }
    if (showIncomplete && excludeIncomplete) {
        parts.push('incomplete')
    }

    return (
        <div className="relative" ref={rootRef}>
            <Button
                variant="link"
                size="xs"
                aria-expanded={open}
                onClick={() => setOpen((prev) => !prev)}
                data-attr="date-exclusions-control"
            >
                {parts.length > 0 ? `Excluding ${parts.join(', ')}` : '+ Exclude'}
            </Button>
            {open && (
                <div className="bg-card absolute bottom-full left-0 z-10 mb-1 flex w-64 flex-col rounded-md border shadow-md">
                    {showIncomplete && (
                        <div className="flex items-center justify-between gap-2 px-3 py-2.5">
                            <Label htmlFor={incompleteId}>Incomplete period</Label>
                            <Switch
                                id={incompleteId}
                                size="sm"
                                checked={excludeIncomplete}
                                onCheckedChange={onExcludeIncompleteChange}
                                data-attr="date-exclusions-incomplete"
                            />
                        </div>
                    )}
                    {showIncomplete && showDays && <Separator />}
                    {showDays && (
                        <div className="flex flex-col gap-2 px-3 py-2.5">
                            <ToggleGroup
                                multiple
                                size="sm"
                                className="w-full"
                                value={excludedDays.map(String)}
                                onValueChange={(days) => onExcludedDaysChange(days.map(Number))}
                            >
                                {Object.keys(DAY_LABELS_SINGLE).map((day) => (
                                    <ToggleGroupItem
                                        key={day}
                                        value={day}
                                        className="flex-1"
                                        aria-label={`Exclude ${DAY_LABELS[Number(day)]}`}
                                        title={`Exclude ${DAY_LABELS[Number(day)]}`}
                                        data-attr={`date-exclusions-day-${day}`}
                                    >
                                        {DAY_LABELS_SINGLE[Number(day)]}
                                    </ToggleGroupItem>
                                ))}
                            </ToggleGroup>
                            <div className="flex items-center justify-center gap-3">
                                <Button variant="link" size="xs" onClick={() => onExcludedDaysChange(WEEKENDS)}>
                                    Weekends
                                </Button>
                                <Button variant="link" size="xs" onClick={() => onExcludedDaysChange(WEEKDAYS)}>
                                    Weekdays
                                </Button>
                                <Button variant="link" size="xs" onClick={() => onExcludedDaysChange([])}>
                                    Clear
                                </Button>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
