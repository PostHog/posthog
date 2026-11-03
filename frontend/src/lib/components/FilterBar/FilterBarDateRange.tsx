import { useValues } from 'kea'
import { useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger, cn } from '@posthog/quill'

import type { DateRangeSelection } from 'lib/components/DateFilter/DateRangePresetsPanel'
import { dateRangeForSelection, selectionForDateRange } from 'lib/components/DateFilter/dateRangeSelection'
import { QuillDateFilter } from 'lib/components/DateFilter/QuillDateFilter'
import { dateFilterToText } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'

import { FilterBarControlChip } from './FilterBarControlChip'
import { useFilterBarControl } from './filterBarControls'

const DEFAULT_DATE_FROM = '-7d'

export interface FilterBarDateRangeProps {
    dateFrom: string | null | undefined
    dateTo: string | null | undefined
    onChange: (dateFrom: string | null, dateTo: string | null) => void
    label?: string
}

/**
 * A date range inside a `FilterBar`. With a range set it shows as a chip; without one it waits in the add menu.
 * The values are PostHog date strings, so `-7d` stays a rolling range and a custom range stays absolute.
 */
export function FilterBarDateRange({
    dateFrom,
    dateTo,
    onChange,
    label = 'Date range',
}: FilterBarDateRangeProps): JSX.Element | null {
    const { weekStartDay } = useValues(teamLogic)
    const [open, setOpen] = useState(false)
    const hasValue = !!dateFrom || !!dateTo

    useFilterBarControl({
        id: 'date-range',
        label,
        icon: IconCalendar,
        hasValue,
        // The add menu closes on the same click, so wait a frame before opening, or its dismissal closes this too.
        open: () => requestAnimationFrame(() => setOpen(true)),
        clear: () => onChange(null, null),
    })

    if (!hasValue && !open) {
        return null
    }

    const valueText = hasValue ? dateFilterToText(dateFrom, dateTo, null) : null
    const apply = (selection: DateRangeSelection): void => {
        const range = dateRangeForSelection(selection)
        onChange(range.date_from ?? null, range.date_to ?? null)
    }

    return (
        <FilterBarControlChip
            icon={IconCalendar}
            label={label}
            onRemove={hasValue ? () => onChange(null, null) : undefined}
            data-attr="filter-bar-date-range"
        >
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger
                    render={
                        <Button
                            variant="outline"
                            className={cn('min-w-0 max-w-64', !valueText && 'text-muted-foreground')}
                        />
                    }
                    data-attr="filter-bar-date-range-value"
                >
                    <span className="truncate">{valueText ?? 'Pick a range'}</span>
                </PopoverTrigger>
                <PopoverContent
                    align="start"
                    collisionAvoidance={{ side: 'flip', align: 'shift', fallbackAxisSide: 'none' }}
                    className="w-auto overflow-hidden border-none p-0 shadow-none ring-0"
                >
                    <QuillDateFilter
                        selection={selectionForDateRange(dateFrom ?? DEFAULT_DATE_FROM, dateTo)}
                        onSelectionChange={(selection) => {
                            apply(selection)
                            // Rolling steppers keep the panel open so the count can be nudged.
                            if (selection.kind !== 'rolling') {
                                setOpen(false)
                            }
                        }}
                        onApplyCustom={(selection) => {
                            apply(selection)
                            setOpen(false)
                        }}
                        weekStartsOn={weekStartDay === 1 ? 1 : 0}
                    />
                </PopoverContent>
            </Popover>
        </FilterBarControlChip>
    )
}
