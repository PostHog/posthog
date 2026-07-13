import { useId } from 'react'

import {
    Button,
    Label,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Separator,
    Switch,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

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
 *  Made for the date filter's `footerExtra` slot. A nested Popover portals the panel out,
 *  so the host popover's overflow can't clip it. */
export function DateExclusionsControl({
    excludedDays,
    onExcludedDaysChange,
    excludeIncomplete,
    onExcludeIncompleteChange,
}: DateExclusionsControlProps): JSX.Element {
    const incompleteId = useId()

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
        <Popover>
            <PopoverTrigger render={<Button variant="link" size="xs" />} data-attr="date-exclusions-control">
                {parts.length > 0 ? `Excluding ${parts.join(', ')}` : '+ Exclude'}
            </PopoverTrigger>
            <PopoverContent side="top" align="start" className="w-64 gap-0 p-0" data-lemon-skin="true">
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
            </PopoverContent>
        </Popover>
    )
}
