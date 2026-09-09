import { useValues } from 'kea'
import { useState } from 'react'

import { IconCalendar } from '@posthog/icons'

import { dateRangeForSelection, selectionForDateRange } from 'lib/components/DateFilter/dateRangeSelection'
import { QuillDateFilter } from 'lib/components/DateFilter/QuillDateFilter'
import { Button, Popover, PopoverContent, PopoverTrigger, SelectTriggerIcon } from 'lib/ui/quill'
import { dateFilterToText, dateMapping } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'

interface TicketDateRangeButtonProps {
    dateFrom: string | null | undefined
    dateTo: string | null | undefined
    onChange: (dateFrom: string | null, dateTo: string | null) => void
}

export function TicketDateRangeButton({ dateFrom, dateTo, onChange }: TicketDateRangeButtonProps): JSX.Element {
    const { weekStartDay } = useValues(teamLogic)
    const [open, setOpen] = useState(false)

    const selection = selectionForDateRange(dateFrom ?? '-7d', dateTo)
    const triggerLabel = dateFilterToText(dateFrom, dateTo, 'Last 7 days', dateMapping, false) ?? 'Last 7 days'

    const applySelection = (nextSelection: Parameters<typeof dateRangeForSelection>[0]): void => {
        const next = dateRangeForSelection(nextSelection)
        onChange(next.date_from ?? null, next.date_to ?? null)
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger render={<Button variant="outline" size="sm" data-attr="date-filter" />}>
                <IconCalendar />
                <span className="text-nowrap">{triggerLabel}</span>
                <SelectTriggerIcon />
            </PopoverTrigger>
            <PopoverContent
                align="start"
                collisionAvoidance={{ side: 'flip', align: 'shift', fallbackAxisSide: 'none' }}
                className="w-auto overflow-hidden border-none p-0 shadow-none ring-0"
            >
                <QuillDateFilter
                    selection={selection}
                    onSelectionChange={(nextSelection) => {
                        applySelection(nextSelection)
                        // Rolling steppers keep the panel open so the count can be nudged.
                        if (nextSelection.kind !== 'rolling') {
                            setOpen(false)
                        }
                    }}
                    onApplyCustom={(nextSelection) => {
                        applySelection(nextSelection)
                        setOpen(false)
                    }}
                    weekStartsOn={weekStartDay === 1 ? 1 : 0}
                />
            </PopoverContent>
        </Popover>
    )
}
