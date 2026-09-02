import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonMenu, type LemonMenuItems } from '@posthog/lemon-ui'

import type {
    CustomerTaskApi,
    CustomerTaskStatusEnumApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { CUSTOMER_TASK_STATUS_TRANSITIONS } from './customerTaskFilters'
import type { customerTasksLogicType } from './customerTasksLogic'
export interface CustomerTaskStatusSelectProps {
    task: CustomerTaskApi
    logic: import('kea').BuiltLogic<customerTasksLogicType>
}
export function CustomerTaskStatusSelect({ task, logic }: CustomerTaskStatusSelectProps): JSX.Element {
    const { mutationKeys } = useValues(logic)
    const { updateTask } = useActions(logic)
    const saving = Boolean(mutationKeys[task.id])
    const items: LemonMenuItems = [
        {
            items: CUSTOMER_TASK_STATUS_TRANSITIONS[task.status].map((status) => ({
                label: statusLabel(status),
                onClick: () => updateTask(task.id, { status }),
            })),
        },
    ]
    return (
        <LemonMenu items={items}>
            <LemonButton
                type="tertiary"
                size="small"
                sideIcon={<IconChevronDown />}
                loading={saving}
                disabledReason={!task.can_edit ? 'You cannot edit this task' : saving ? 'Saving' : undefined}
                data-attr="customer-task-status"
            >
                {statusLabel(task.status)}
            </LemonButton>
        </LemonMenu>
    )
}
function statusLabel(status: CustomerTaskStatusEnumApi): string {
    return status === 'in_progress' ? 'In progress' : status.charAt(0).toUpperCase() + status.slice(1)
}
