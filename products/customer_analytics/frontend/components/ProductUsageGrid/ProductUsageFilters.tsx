import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { AccountAssignmentFilter } from 'lib/components/AccountAssignmentFilter/AccountAssignmentFilter'

import { productUsageGridLogic } from './productUsageGridLogic'

export function ProductUsageFilters(): JSX.Element {
    const { controls, result, user } = useValues(productUsageGridLogic)
    const { setControls } = useActions(productUsageGridLogic)
    const mine = !!user && controls.assignedTo.length === 1 && controls.assignedTo[0] === user.id
    return (
        <div className="flex flex-wrap items-center gap-2" data-attr="product-activity-filters">
            <LemonInput
                type="search"
                value={controls.search}
                onChange={(search) => setControls({ search })}
                placeholder="Search accounts"
                size="small"
                data-attr="product-activity-search"
            />
            <AccountAssignmentFilter
                assignedToUserIds={controls.assignedTo}
                status={controls.assignmentStatus}
                onAssignedToUserIdsChange={(assignedTo) => setControls({ assignedTo })}
                onStatusChange={(assignmentStatus) => setControls({ assignmentStatus })}
            />
            <LemonSelect
                value={controls.relationshipId}
                onChange={(relationshipId) => setControls({ relationshipId })}
                size="small"
                options={[
                    { value: null, label: 'All roles' },
                    ...(result?.accounts.relationshipDefinitions ?? []).map((role) => ({
                        value: role.id,
                        label: role.name,
                    })),
                ]}
                data-attr="product-activity-role"
            />
            <LemonCheckbox
                label="My accounts"
                checked={mine}
                onChange={(checked) =>
                    setControls({ assignedTo: checked && user ? [user.id] : [], assignmentStatus: 'all' })
                }
            />
        </div>
    )
}
