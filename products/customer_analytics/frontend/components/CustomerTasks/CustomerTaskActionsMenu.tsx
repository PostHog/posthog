import { useActions, useValues } from 'kea'

import { IconArchive, IconEllipsis, IconUndo } from '@posthog/icons'
import { LemonButton, LemonMenu, type LemonMenuItems } from '@posthog/lemon-ui'

import type { CustomerTaskApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { customerTasksLogicType } from './customerTasksLogic'
export interface CustomerTaskActionsMenuProps {
    task: CustomerTaskApi
    logic: import('kea').BuiltLogic<customerTasksLogicType>
}
export function CustomerTaskActionsMenu({ task, logic }: CustomerTaskActionsMenuProps): JSX.Element {
    const { mutationKeys } = useValues(logic)
    const { archiveTask, restoreTask } = useActions(logic)
    const saving = Boolean(mutationKeys[task.id])
    const archived = Boolean(task.archived_at)
    const items: LemonMenuItems = [
        {
            items: [
                {
                    label: archived ? 'Restore task' : 'Archive task',
                    icon: archived ? <IconUndo /> : <IconArchive />,
                    onClick: () => (archived ? restoreTask(task.id) : archiveTask(task.id)),
                },
            ],
        },
    ]
    return (
        <LemonMenu items={items}>
            <LemonButton
                type="tertiary"
                size="small"
                icon={<IconEllipsis />}
                loading={saving}
                disabledReason={!task.can_edit ? 'You cannot edit this task' : saving ? 'Saving' : undefined}
                aria-label="Task actions"
                data-attr="customer-task-actions"
            />
        </LemonMenu>
    )
}
