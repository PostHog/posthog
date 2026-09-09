import { useActions } from 'kea'
import { useEffect, useState } from 'react'

import { Popover, PopoverContent, PopoverTrigger } from 'lib/ui/quill'

import { AssigneeResolver } from './AssigneeDisplay'
import { AssigneeDropdown } from './AssigneeDropdown'
import { assigneeSelectLogic } from './assigneeSelectLogic'
import { Assignee, TicketAssignee } from './types'

export const AssigneeSelect = ({
    assignee,
    onChange,
    children,
    disabledReason,
    loadOnOpen = false,
}: {
    assignee: TicketAssignee
    onChange: (assignee: TicketAssignee) => void
    children: (assignee: Assignee, isOpen: boolean) => JSX.Element
    disabledReason?: string
    loadOnOpen?: boolean
}): JSX.Element => {
    const { setSearch, ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)
    const [showPopover, setShowPopover] = useState(false)

    const _onChange = (value: TicketAssignee): void => {
        setSearch('')
        setShowPopover(false)
        onChange(value)
    }

    useEffect(() => {
        if (!loadOnOpen) {
            ensureAssigneeTypesLoaded()
        }
    }, [ensureAssigneeTypesLoaded, loadOnOpen])

    return (
        <AssigneeResolver assignee={assignee}>
            {({ assignee: resolvedAssignee }) =>
                disabledReason ? (
                    children(resolvedAssignee, false)
                ) : (
                    <Popover
                        open={showPopover}
                        onOpenChange={(visible) => {
                            setShowPopover(visible)
                            if (visible && loadOnOpen) {
                                ensureAssigneeTypesLoaded()
                            }
                            if (!visible) {
                                setSearch('')
                            }
                        }}
                    >
                        <PopoverTrigger render={children(resolvedAssignee, showPopover)} />
                        <PopoverContent align="end" className="w-auto p-1">
                            <AssigneeDropdown assignee={assignee} onChange={_onChange} />
                        </PopoverContent>
                    </Popover>
                )
            }
        </AssigneeResolver>
    )
}
