import { useActions, useValues } from 'kea'

import { LemonButton, ProfilePicture } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { fullName } from 'lib/utils/strings'

import type { CustomerTaskApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { customerTaskEditDisabledReason } from './customerTaskFilters'
import type { customerTasksLogicType } from './customerTasksLogic'
export interface CustomerTaskAssigneeSelectProps {
    task: CustomerTaskApi
    logic: import('kea').BuiltLogic<customerTasksLogicType>
}
export function CustomerTaskAssigneeSelect({ task, logic }: CustomerTaskAssigneeSelectProps): JSX.Element {
    const { mutationKeys } = useValues(logic)
    const { updateTask } = useActions(logic)
    const saving = Boolean(mutationKeys[task.id])
    return (
        <MemberSelect
            value={task.assigned_to?.id ?? null}
            defaultLabel="Unassigned"
            allowNone
            type="tertiary"
            size="small"
            onChange={(user) => updateTask(task.id, { assigned_to_id: user?.id ?? null })}
        >
            {(selected) => {
                // MemberSelect resolves selected from the member list, which loads only after the picker opens.
                const assignee = selected ?? task.assigned_to
                return (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        loading={saving}
                        disabledReason={customerTaskEditDisabledReason(task) ?? (saving ? 'Saving' : undefined)}
                        icon={assignee ? <ProfilePicture user={{ email: assignee.email }} size="sm" /> : undefined}
                        data-attr="customer-task-assignee"
                    >
                        {assignee ? fullName(assignee) || assignee.email : 'Unassigned'}
                    </LemonButton>
                )
            }}
        </MemberSelect>
    )
}
