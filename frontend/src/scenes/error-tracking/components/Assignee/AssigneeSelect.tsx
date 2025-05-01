import { LemonDropdown } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { useEffect, useState } from 'react'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeResolver } from './AssigneeDisplay'
import { AssigneeDropdown } from './AssigneeDropdown'
import { Assignee, assigneeSelectLogic } from './assigneeSelectLogic'

export const AssigneeSelect = ({
    assignee,
    onChange,
    children,
}: {
    assignee: ErrorTrackingIssue['assignee']
    onChange: (assignee: ErrorTrackingIssue['assignee']) => void
    children: (assignee: Assignee) => JSX.Element
}): JSX.Element => {
    const { setSearch, ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)
    const [showPopover, setShowPopover] = useState(false)

    const _onChange = (value: ErrorTrackingIssue['assignee']): void => {
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
                    {({ assignee: resolvedAssignee }) => children(resolvedAssignee)}
                </AssigneeResolver>
            </div>
        </LemonDropdown>
    )
}
