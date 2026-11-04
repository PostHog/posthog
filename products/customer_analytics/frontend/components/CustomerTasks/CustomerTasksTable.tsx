import './CustomerTasksTable.scss'

import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDropdown, LemonInputSelect, LemonMenu, LemonSkeleton } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjsLocalToTimezone } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonTable, type LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { CustomerTaskApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { CustomerTaskActionsMenu } from './CustomerTaskActionsMenu'
import { CustomerTaskAssigneeSelect } from './CustomerTaskAssigneeSelect'
import { CustomerTaskDueAtInput } from './CustomerTaskDueAtInput'
import {
    CUSTOMER_TASK_STATUS_TRANSITIONS,
    customerTaskEditDisabledReason,
    type CustomerTasksContext,
} from './customerTaskFilters'
import { CustomerTaskModal } from './CustomerTaskModal'
import { CustomerTasksFilters } from './CustomerTasksFilters'
import type { customerTasksLogicType } from './customerTasksLogic'
import { CustomerTaskStatusSelect } from './CustomerTaskStatusSelect'

export interface CustomerTasksTableProps {
    logic: import('kea').BuiltLogic<customerTasksLogicType>
    context: CustomerTasksContext
    canCreate?: boolean
    canViewAll?: boolean
    embedded?: boolean
}
export function CustomerTasksTable({
    logic,
    context,
    canCreate = false,
    canViewAll = false,
    embedded = true,
}: CustomerTasksTableProps): JSX.Element {
    const {
        taskPage,
        taskPageError,
        taskPageLoading,
        tasks,
        pagination,
        hasActiveFilters,
        taskSorting,
        timezone,
        filters,
        page,
        ordering,
        mutationKeys,
        accountOptions,
        accountOptionsResponseLoading,
        bulkAccountOpen,
    } = useValues(logic)
    const {
        loadTaskPage,
        openCreateModal,
        openEditModal,
        setTaskSorting,
        bulkUpdateTasks,
        loadAccountOptions,
        setBulkAccountOpen,
    } = useActions(logic)
    const bulkSaving = Boolean(mutationKeys.bulk)
    const bulkDisabledReason = bulkSaving ? 'Saving' : taskPageLoading ? 'Loading tasks' : undefined
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
            title: 'Task',
            key: 'name',
            width: '35%',
            sorter: true,
            render: (_, task) => (
                <div className="flex min-w-0 flex-col gap-1 py-1">
                    <Link
                        subtle
                        className="font-semibold"
                        onClick={() => openEditModal(task)}
                        data-attr="customer-task-name"
                    >
                        {task.name}
                    </Link>
                    {task.description?.trim() && (
                        <span className="text-xs text-muted line-clamp-2">{task.description}</span>
                    )}
                    <div className="CustomerTasksTable__narrow-assignee">
                        <CustomerTaskAssigneeSelect task={task} logic={logic} />
                    </div>
                    <div className="CustomerTasksTable__narrow-controls flex-wrap items-center gap-1">
                        <CustomerTaskStatusSelect task={task} logic={logic} />
                        <CustomerTaskDueAtInput task={task} logic={logic} timezone={timezone} />
                    </div>
                </div>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            className: 'CustomerTasksTable__status',
            width: 130,
            sorter: true,
            render: (_, task) => <CustomerTaskStatusSelect task={task} logic={logic} />,
        },
        ...(context === 'inbox'
            ? [
                  {
                      title: 'Account',
                      key: 'account',
                      sorter: true as const,
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
            sorter: true,
            render: (_, task) => <CustomerTaskAssigneeSelect task={task} logic={logic} />,
        },
        {
            title: 'Due',
            key: 'due_at',
            className: 'CustomerTasksTable__due',
            width: 170,
            sorter: true,
            render: (_, task) => <CustomerTaskDueAtInput task={task} logic={logic} timezone={timezone} />,
        },
        {
            title: 'Updated',
            key: 'updated_at',
            className: 'CustomerTasksTable__updated',
            sorter: true,
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
        <div className={`CustomerTasksTable CustomerTasksTable--${context}`} data-attr="customer-tasks-table">
            <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
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
            <LemonTable<CustomerTaskApi, string>
                embedded={embedded}
                dataSource={tasks}
                columns={columns}
                rowKey="id"
                sorting={taskSorting}
                onSort={setTaskSorting}
                useURLForSorting={false}
                noSortingCancellation
                loading={taskPageLoading}
                pagination={pagination}
                emptyState={empty}
                nouns={['task', 'tasks']}
                tableLayout="fixed"
                bulkSelection={{
                    actionsPlacement: 'start',
                    barClassName: 'mb-2 flex-wrap justify-start! pl-0!',
                    noun: ['task', 'tasks'],
                    rowAriaLabel: (task) => `Select task ${task.name}`,
                    headerAriaLabel: 'Select all tasks on this page',
                    clearSelectionKey: JSON.stringify({ filters, page, ordering }),
                    isRowSelectable: (task) => {
                        const disabledReason =
                            (task.archived_at
                                ? task.can_restore
                                    ? undefined
                                    : 'You cannot restore this task'
                                : customerTaskEditDisabledReason(task)) ??
                            (mutationKeys[task.id] ? 'Saving' : bulkDisabledReason)
                        return disabledReason ? { disabledReason } : true
                    },
                    renderActions: ({ selectedKeys, selectedRecords, setSelectedKeys }) => {
                        const editDisabledReason =
                            bulkDisabledReason ??
                            (selectedRecords.some((task) => task.archived_at)
                                ? 'Unarchive the selected tasks to edit them'
                                : undefined)
                        return (
                            <>
                                <LemonMenu
                                    items={[
                                        {
                                            items: (['open', 'in_progress', 'completed', 'canceled'] as const).map(
                                                (status) => ({
                                                    label:
                                                        status === 'in_progress'
                                                            ? 'In progress'
                                                            : status.charAt(0).toUpperCase() + status.slice(1),
                                                    disabledReason: selectedRecords.every(
                                                        (task) =>
                                                            task.status === status ||
                                                            CUSTOMER_TASK_STATUS_TRANSITIONS[task.status].includes(
                                                                status
                                                            )
                                                    )
                                                        ? editDisabledReason
                                                        : 'Some selected tasks cannot change to this status',
                                                    onClick: () =>
                                                        bulkUpdateTasks([...selectedKeys], { status }, setSelectedKeys),
                                                })
                                            ),
                                        },
                                    ]}
                                >
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        loading={bulkSaving}
                                        disabledReason={editDisabledReason}
                                        data-attr="customer-tasks-bulk-status"
                                    >
                                        Change status
                                    </LemonButton>
                                </LemonMenu>
                                <MemberSelect
                                    value={null}
                                    defaultLabel="Unassigned"
                                    allowNone
                                    onChange={(user) =>
                                        bulkUpdateTasks(
                                            [...selectedKeys],
                                            { assigned_to_id: user?.id ?? null },
                                            setSelectedKeys
                                        )
                                    }
                                >
                                    {() => (
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            loading={bulkSaving}
                                            disabledReason={editDisabledReason}
                                            data-attr="customer-tasks-bulk-assignee"
                                        >
                                            Assign to
                                        </LemonButton>
                                    )}
                                </MemberSelect>
                                <LemonCalendarSelectInput
                                    value={null}
                                    onChange={(value) =>
                                        bulkUpdateTasks(
                                            [...selectedKeys],
                                            {
                                                due_at: value
                                                    ? dayjsLocalToTimezone(
                                                          value.format('YYYY-MM-DDTHH:mm'),
                                                          timezone
                                                      ).toISOString()
                                                    : null,
                                            },
                                            setSelectedKeys
                                        )
                                    }
                                    granularity="minute"
                                    use24HourFormat
                                    placeholder="Due at"
                                    buttonProps={{
                                        type: 'secondary',
                                        size: 'small',
                                        fullWidth: false,
                                        loading: bulkSaving,
                                        disabledReason: editDisabledReason,
                                        'data-attr': 'customer-tasks-bulk-due',
                                        sideAction: {
                                            icon: <IconX />,
                                            onClick: () =>
                                                bulkUpdateTasks([...selectedKeys], { due_at: null }, setSelectedKeys),
                                            disabledReason: editDisabledReason,
                                            'aria-label': 'Clear due dates',
                                        },
                                    }}
                                />
                                <LemonDropdown
                                    visible={bulkAccountOpen}
                                    closeOnClickInside={false}
                                    onVisibilityChange={(open) => {
                                        setBulkAccountOpen(open)
                                        if (open) {
                                            loadAccountOptions({ query: '' })
                                        }
                                    }}
                                    overlay={
                                        <div className="w-64 p-2">
                                            <LemonInputSelect
                                                mode="single"
                                                value={[]}
                                                options={[
                                                    { key: 'none', label: 'No account' },
                                                    ...accountOptions.map((account) => ({
                                                        key: account.id,
                                                        label: account.name,
                                                    })),
                                                ]}
                                                loading={accountOptionsResponseLoading}
                                                onInputChange={(query) => loadAccountOptions({ query })}
                                                onChange={(values) => {
                                                    if (values[0]) {
                                                        bulkUpdateTasks(
                                                            [...selectedKeys],
                                                            { account_id: values[0] === 'none' ? null : values[0] },
                                                            setSelectedKeys
                                                        )
                                                    }
                                                }}
                                                placeholder="Search accounts"
                                                disabledReason={editDisabledReason}
                                            />
                                        </div>
                                    }
                                >
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        loading={bulkSaving}
                                        disabledReason={editDisabledReason}
                                        data-attr="customer-tasks-bulk-account"
                                    >
                                        Account
                                    </LemonButton>
                                </LemonDropdown>
                                <LemonMenu
                                    items={[
                                        {
                                            label: 'Archive tasks',
                                            disabledReason:
                                                bulkDisabledReason ??
                                                (selectedRecords.every((task) => task.archived_at)
                                                    ? 'The selected tasks are already archived'
                                                    : undefined),
                                            onClick: () =>
                                                bulkUpdateTasks([...selectedKeys], { archived: true }, setSelectedKeys),
                                        },
                                        {
                                            label: 'Unarchive tasks',
                                            disabledReason:
                                                bulkDisabledReason ??
                                                (selectedRecords.every((task) => !task.archived_at)
                                                    ? 'The selected tasks are already active'
                                                    : undefined),
                                            onClick: () =>
                                                bulkUpdateTasks(
                                                    [...selectedKeys],
                                                    { archived: false },
                                                    setSelectedKeys
                                                ),
                                        },
                                    ]}
                                >
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        loading={bulkSaving}
                                        disabledReason={bulkDisabledReason}
                                        data-attr="customer-tasks-bulk-archive"
                                    >
                                        Archive/unarchive
                                    </LemonButton>
                                </LemonMenu>
                            </>
                        )
                    },
                }}
            />
            <CustomerTaskModal logic={logic} context={context} />
        </div>
    )
}
