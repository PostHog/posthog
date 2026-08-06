import { IconChevronRight } from '@posthog/icons'
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

import type { DataAttributeProps } from 'lib/components/DateFilter/DateRangePresetsPanel'

/** Exclusions footer row for the quill DateTimePicker's presets panel: a flyout with an
 * incomplete-period switch and exclude-day chips. Speaks _excluded_ ISO days ('1'–'7'). */

export interface DateFilterExclusions {
    days: string[]
    incomplete: boolean
}

export function dateFilterExclusionParts({ days, incomplete }: DateFilterExclusions): string[] {
    const parts: string[] = []
    if (days.length > 0) {
        const sorted = [...days].sort().join(',')
        if (sorted === '6,7') {
            parts.push('weekends')
        } else if (sorted === '1,2,3,4,5') {
            parts.push('weekdays')
        } else {
            parts.push(`${days.length} ${days.length === 1 ? 'day' : 'days'}`)
        }
    }
    if (incomplete) {
        parts.push('incomplete')
    }
    return parts
}

export function dateFilterExclusionsSummary(exclusions: DateFilterExclusions): string {
    const parts = dateFilterExclusionParts(exclusions)
    return parts.length > 0 ? `Excluding ${parts.join(', ')}` : ''
}

const DAY_LABELS: Record<string, string> = {
    1: 'M',
    2: 'T',
    3: 'W',
    4: 'T',
    5: 'F',
    6: 'S',
    7: 'S',
}

export function DateFilterExclusionsControl({
    exclusions,
    onChange,
    showDays,
    showIncomplete,
    panelProps,
}: {
    exclusions: DateFilterExclusions
    onChange: (exclusions: DateFilterExclusions) => void
    showDays: boolean
    showIncomplete: boolean
    panelProps?: DataAttributeProps
}): JSX.Element {
    const summary = dateFilterExclusionsSummary(exclusions)
    return (
        <Popover>
            <PopoverTrigger
                render={<Button variant="default" size="sm" left className="w-full" />}
                data-attr="date-filter-exclusions"
            >
                {summary || 'Exclude'}
                <IconChevronRight className="ms-auto" />
            </PopoverTrigger>
            <PopoverContent side="right" align="end" {...panelProps} className="w-64 gap-0 p-0">
                {showIncomplete && (
                    <div className="flex items-center justify-between gap-2 px-3 py-2.5">
                        <Label htmlFor="date-filter-exclude-incomplete">Incomplete period</Label>
                        <Switch
                            id="date-filter-exclude-incomplete"
                            size="sm"
                            checked={exclusions.incomplete}
                            onCheckedChange={(incomplete) => onChange({ ...exclusions, incomplete })}
                        />
                    </div>
                )}
                {showIncomplete && showDays && <Separator />}
                {showDays && (
                    <div className="flex flex-col gap-2 px-3 py-2.5">
                        <ToggleGroup
                            multiple
                            size="sm"
                            spacing={1}
                            className="w-full"
                            value={exclusions.days}
                            onValueChange={(days) => onChange({ ...exclusions, days })}
                        >
                            {Object.keys(DAY_LABELS).map((day) => (
                                <ToggleGroupItem
                                    key={day}
                                    value={day}
                                    className="flex-1 data-[pressed]:border-primary data-[pressed]:bg-primary/10 data-[pressed]:text-primary"
                                    aria-label={`Exclude day ${day}`}
                                >
                                    {DAY_LABELS[day]}
                                </ToggleGroupItem>
                            ))}
                        </ToggleGroup>
                        <div className="flex items-center justify-center gap-3">
                            <Button
                                variant="link-muted"
                                size="xs"
                                onClick={() => onChange({ ...exclusions, days: ['6', '7'] })}
                            >
                                Weekends
                            </Button>
                            <Button
                                variant="link-muted"
                                size="xs"
                                onClick={() => onChange({ ...exclusions, days: ['1', '2', '3', '4', '5'] })}
                            >
                                Weekdays
                            </Button>
                            <Button
                                variant="link-muted"
                                size="xs"
                                onClick={() => onChange({ ...exclusions, days: [] })}
                            >
                                Clear
                            </Button>
                        </div>
                    </div>
                )}
            </PopoverContent>
        </Popover>
    )
}
