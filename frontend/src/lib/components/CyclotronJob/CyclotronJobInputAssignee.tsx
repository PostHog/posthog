import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import {
    AssigneeDropdown,
    AssigneeIconDisplay,
    AssigneeLabelDisplay,
    assigneeSelectLogic,
    TicketAssignee,
} from 'products/conversations/frontend/components/Assignee'

export interface CyclotronJobInputAssigneeProps {
    value: TicketAssignee
    onChange: (value: TicketAssignee) => void
}

export function CyclotronJobInputAssignee({ value, onChange }: CyclotronJobInputAssigneeProps): JSX.Element {
    const { ensureAssigneeTypesLoaded, setSearch } = useActions(assigneeSelectLogic)
    const { resolveAssignee } = useValues(assigneeSelectLogic)
    const [showPopover, setShowPopover] = useState(false)

    useEffect(() => {
        ensureAssigneeTypesLoaded()
    }, [ensureAssigneeTypesLoaded])

    const handleChange = (newValue: TicketAssignee): void => {
        setSearch('')
        setShowPopover(false)
        onChange(newValue)
    }

    const resolvedAssignee = resolveAssignee(value)

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            onVisibilityChange={(visible) => setShowPopover(visible)}
            overlay={<AssigneeDropdown assignee={value} onChange={handleChange} />}
        >
            <LemonButton type="secondary" sideIcon={<IconChevronDown />} fullWidth>
                <span className="flex items-center gap-1">
                    <AssigneeIconDisplay assignee={resolvedAssignee} size="small" />
                    <AssigneeLabelDisplay assignee={resolvedAssignee} size="small" />
                </span>
            </LemonButton>
        </LemonDropdown>
    )
}
