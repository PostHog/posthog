import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger, SelectTriggerIcon } from '@posthog/quill'

import type { DateRangeSelection } from 'lib/components/DateFilter/DateRangePresetsPanel'
import { dateRangeForSelection, selectionForDateRange } from 'lib/components/DateFilter/dateRangeSelection'
import { QuillDateFilter } from 'lib/components/DateFilter/QuillDateFilter'
import { dateFilterToText } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'

// The list reads no range as all time, which the date strings spell 'all'.
const ALL_TIME = 'all'

/** The ticket list's date range: a quill trigger over the quill date picker, writing the same strings as `DateFilter`. */
export function QuillTicketDateFilter(): JSX.Element {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const { dateFrom, dateTo } = useValues(logic)
    const { setDateRange } = useActions(logic)
    const { weekStartDay } = useValues(teamLogic)
    const [open, setOpen] = useState(false)

    const applySelection = (selection: DateRangeSelection): void => {
        const { date_from, date_to } = dateRangeForSelection(selection)
        setDateRange(date_from ?? null, date_to ?? null)
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger render={<Button variant="outline" data-attr="ticket-date-filter" />}>
                <IconCalendar />
                <span className="truncate">{dateFilterToText(dateFrom ?? ALL_TIME, dateTo, 'Custom')}</span>
                <SelectTriggerIcon />
            </PopoverTrigger>
            <PopoverContent
                align="start"
                collisionAvoidance={{ side: 'flip', align: 'shift', fallbackAxisSide: 'none' }}
                className="w-auto overflow-hidden border-none p-0 shadow-none ring-0"
            >
                <QuillDateFilter
                    selection={selectionForDateRange(dateFrom ?? ALL_TIME, dateTo)}
                    onSelectionChange={(selection) => {
                        applySelection(selection)
                        // Rolling steppers keep the panel open so the count can be nudged.
                        if (selection.kind !== 'rolling') {
                            setOpen(false)
                        }
                    }}
                    onApplyCustom={(selection) => {
                        applySelection(selection)
                        setOpen(false)
                    }}
                    weekStartsOn={weekStartDay === 1 ? 1 : 0}
                />
            </PopoverContent>
        </Popover>
    )
}
