import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'
import { Button, Popover, PopoverContent, PopoverTrigger, SelectTriggerIcon } from 'lib/ui/quill'

import { AssigneeIconDisplay, AssigneeLabelDisplay } from './AssigneeDisplay'
import { AssigneeDropdown } from './AssigneeDropdown'
import { assigneeSelectLogic } from './assigneeSelectLogic'
import type { TicketAssignee } from './types'

export default function CyclotronJobInputAssignee({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const { ensureAssigneeTypesLoaded, setSearch } = useActions(assigneeSelectLogic)
    const { resolveAssignee } = useValues(assigneeSelectLogic)
    const [open, setOpen] = useState(false)

    useEffect(() => {
        ensureAssigneeTypesLoaded()
    }, [ensureAssigneeTypesLoaded])

    const handleChange = (newValue: TicketAssignee): void => {
        setSearch('')
        setOpen(false)
        onChange(newValue)
    }

    const resolvedAssignee = resolveAssignee(value)

    return (
        <Popover
            open={open}
            onOpenChange={(nextOpen) => {
                setOpen(nextOpen)
                if (!nextOpen) {
                    setSearch('')
                }
            }}
        >
            <PopoverTrigger render={<Button variant="outline" className="w-full" />}>
                <span className="flex min-w-0 items-center gap-1">
                    <AssigneeIconDisplay assignee={resolvedAssignee} size="small" />
                    <AssigneeLabelDisplay assignee={resolvedAssignee} size="small" />
                </span>
                <SelectTriggerIcon />
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto p-1">
                <AssigneeDropdown assignee={value} onChange={handleChange} />
            </PopoverContent>
        </Popover>
    )
}
