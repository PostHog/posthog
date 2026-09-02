import './CustomerTasksTable.scss'

import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, type LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { CustomerTaskApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { CustomerTaskActionsMenu } from './CustomerTaskActionsMenu'
import { CustomerTaskAssigneeSelect } from './CustomerTaskAssigneeSelect'
import { CustomerTaskDueAtInput } from './CustomerTaskDueAtInput'
import type { CustomerTasksContext } from './customerTaskFilters'
import { CustomerTaskModal } from './CustomerTaskModal'
import { CustomerTasksFilters } from './CustomerTasksFilters'
import type { customerTasksLogicType } from './customerTasksLogic'
import { CustomerTaskStatusSelect } from './CustomerTaskStatusSelect'

export interface CustomerTasksTableProps {
    logic: import('kea').BuiltLogic<customerTasksLogicType>
    context: CustomerTasksContext
    canCreate?: boolean
    canViewAll?: boolean
    accountName?: string
}
export function CustomerTasksTable({
    logic,
    context,
    canCreate = false,
    canViewAll = false,
}: CustomerTasksTableProps): JSX.Element {
    const { taskPage, taskPageError, taskPageLoading, tasks, pagination, hasActiveFilters, timezone } = useValues(logic)
    const { loadTaskPage, openCreateModal, openEditModal } = useActions(logic)
    if (taskPage === null && taskPageLoading) {
        return <LemonSkeleton className="h-64 w-full" />
    }
    if (taskPageError && taskPage === null) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadTaskPage }}>
                Couldn't load tasks. Try again.
            </LemonBanner>
        )
    }
    const columns: LemonTableColumns<CustomerTaskApi> = [
        {
            title: 'Status',
            key: 'status',
            width: 130,
            render: (_, task) => <CustomerTaskStatusSelect task={task} logic={logic} />,
        },
        {
            title: 'Task',
            key: 'name',
            width: '35%',
            render: (_, task) => (
                <div className="min-w-0">
                    <LemonButton
                        type="tertiary"
                        size="small"
                        className="max-w-full truncate font-semibold"
                        onClick={() => openEditModal(task)}
                        data-attr="customer-task-name"
                    >
                        {task.name}
                    </LemonButton>
                    <div className="CustomerTasksTable__narrow-assignee">
                        <CustomerTaskAssigneeSelect task={task} logic={logic} />
                    </div>
                </div>
            ),
        },
        ...(context === 'inbox'
            ? [
                  {
                      title: 'Account',
                      key: 'account',
                      render: (_: unknown, task: CustomerTaskApi) =>
                          task.account ? (
                              <Link to={urls.customerAnalyticsAccount(task.account.id, 'tasks')}>
                                  {task.account.name}
                              </Link>
                          ) : (
                              <span className="text-muted">No account</span>
                          ),
                  },
              ]
            : []),
        {
            title: 'Assignee',
            key: 'assigned_to',
            className: 'CustomerTasksTable__assignee',
            render: (_, task) => <CustomerTaskAssigneeSelect task={task} logic={logic} />,
        },
        {
            title: 'Due',
            key: 'due_at',
            width: 170,
            render: (_, task) => <CustomerTaskDueAtInput task={task} logic={logic} timezone={timezone} />,
        },
        {
            title: 'Updated',
            key: 'updated_at',
            className: 'CustomerTasksTable__updated',
            render: (_, task) => <TZLabel time={task.updated_at} />,
        },
        {
            title: '',
            key: 'actions',
            width: 48,
            render: (_, task) => <CustomerTaskActionsMenu task={task} logic={logic} />,
        },
    ]
    const empty = (
        <div className="flex flex-col items-center gap-2 py-6">
            <span>
                {hasActiveFilters
                    ? 'No tasks match these filters.'
                    : context === 'account'
                      ? 'No open tasks for this account.'
                      : 'No open tasks are assigned to you.'}
            </span>
            {canCreate && !hasActiveFilters && (
                <LemonButton type="primary" size="small" onClick={openCreateModal}>
                    Create task
                </LemonButton>
            )}
        </div>
    )
    return (
        <div className="CustomerTasksTable" data-attr="customer-tasks-table">
            <div className="mb-4 flex items-center justify-between gap-2">
                <CustomerTasksFilters logic={logic} context={context} canViewAll={canViewAll} />
                {canCreate && (
                    <LemonButton type="primary" size="small" onClick={openCreateModal}>
                        New task
                    </LemonButton>
                )}
            </div>
            {Boolean(taskPageError) && (
                <LemonBanner className="mb-3" type="error" action={{ children: 'Try again', onClick: loadTaskPage }}>
                    Couldn't load tasks. Try again.
                </LemonBanner>
            )}
            <LemonTable<CustomerTaskApi>
                dataSource={tasks}
                columns={columns}
                rowKey="id"
                loading={taskPageLoading}
                pagination={pagination}
                emptyState={empty}
                nouns={['task', 'tasks']}
                tableLayout="fixed"
            />
            <CustomerTaskModal logic={logic} />
        </div>
    )
}
