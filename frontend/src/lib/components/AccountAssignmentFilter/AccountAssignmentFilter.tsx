import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDivider, LemonDropdown } from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'

import type { AssignmentStatus } from './accountAssignmentFilterTypes'

export interface AccountAssignmentFilterDataAttrs {
    trigger?: string
    unassigned?: string
    assigned?: string
    all?: string
}

export interface AccountAssignmentFilterProps {
    assignedToUserIds: number[]
    status: AssignmentStatus
    onAssignedToUserIdsChange: (userIds: number[]) => void
    onStatusChange: (status: AssignmentStatus) => void
    dataAttrs?: AccountAssignmentFilterDataAttrs
}

export function AccountAssignmentFilter({
    assignedToUserIds,
    status,
    onAssignedToUserIdsChange,
    onStatusChange,
    dataAttrs,
}: AccountAssignmentFilterProps): JSX.Element {
    const buttonLabel =
        status === 'unassigned'
            ? 'Unassigned only'
            : status === 'all'
              ? 'All accounts'
              : assignedToUserIds.length === 0
                ? 'Assigned to anyone'
                : assignedToUserIds.length === 1
                  ? 'Assigned to 1 person'
                  : `Assigned to ${assignedToUserIds.length} people`

    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={
                <div className="p-2 min-w-64 flex flex-col gap-2">
                    <LemonCheckbox
                        checked={status === 'unassigned'}
                        onChange={(checked) => checked && onStatusChange('unassigned')}
                        label="Unassigned only"
                        data-attr={dataAttrs?.unassigned}
                    />
                    <LemonCheckbox
                        checked={status === 'assigned'}
                        onChange={(checked) => checked && onStatusChange('assigned')}
                        label="Assigned to anyone"
                        data-attr={dataAttrs?.assigned}
                    />
                    <LemonCheckbox
                        checked={status === 'all'}
                        onChange={(checked) => checked && onStatusChange('all')}
                        label="All assignment statuses"
                        data-attr={dataAttrs?.all}
                    />
                    <LemonDivider className="my-0" />
                    <MemberSelectMultiple
                        idKey="id"
                        value={assignedToUserIds}
                        onChange={(users) => onAssignedToUserIdsChange(users.map((user) => user.id))}
                    />
                </div>
            }
        >
            <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />} data-attr={dataAttrs?.trigger}>
                {buttonLabel}
            </LemonButton>
        </LemonDropdown>
    )
}
