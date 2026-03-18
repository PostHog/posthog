import { useActions } from 'kea'
import { useEffect, useState } from 'react'

import { LemonDropdown } from '@posthog/lemon-ui'

import { AssigneeResolver } from './AssigneeDisplay'
import { AssigneeDropdown } from './AssigneeDropdown'
import { assigneeSelectLogic } from './assigneeSelectLogic'
import { Assignee, TicketAssignee } from './types'

export const AssigneeSelect = ({
    assignee,
    onChange,
    children,
}: {
    assignee: TicketAssignee
    onChange: (assignee: TicketAssignee) => void
    children: (assignee: Assignee, isOpen: boolean) => JSX.Element
}): JSX.Element => {
    const { setSearch, ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)
    const [showPopover, setShowPopover] = useState(false)

    const _onChange = (value: TicketAssignee): void => {
        setSearch('')
        setShowPopover(false)
        onChange(value)
    }

    useEffect(() => {
        ensureAssigneeTypesLoaded()
    }, [ensureAssigneeTypesLoaded])

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            onVisibilityChange={(visible) => setShowPopover(visible)}
            overlay={<AssigneeDropdown assignee={assignee} onChange={_onChange} />}
        >
            <div>
                <AssigneeResolver assignee={assignee}>
                    {({ assignee: resolvedAssignee }) => children(resolvedAssignee, showPopover)}
                </AssigneeResolver>
            </div>
        </LemonDropdown>
    )
}
