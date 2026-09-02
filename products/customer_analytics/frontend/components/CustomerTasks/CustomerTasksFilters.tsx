import { useActions, useValues } from 'kea'

import { IconChevronDown, IconFilter, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonDropdown,
    LemonInput,
    LemonInputSelect,
    LemonMenu,
    type LemonMenuItems,
} from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'

import type { CustomerTaskAssigneeFilter, CustomerTasksContext } from './customerTaskFilters'
import {
    CUSTOMER_TASK_ARCHIVE_OPTIONS,
    CUSTOMER_TASK_DUE_OPTIONS,
    CUSTOMER_TASK_STATUS_OPTIONS,
} from './customerTaskFilters'
import type { customerTasksLogicType } from './customerTasksLogic'
export interface CustomerTasksFiltersProps {
    logic: import('kea').BuiltLogic<customerTasksLogicType>
    context: CustomerTasksContext
    canViewAll?: boolean
}
export function CustomerTasksFilters({ logic, context, canViewAll = false }: CustomerTasksFiltersProps): JSX.Element {
    const { filters, hasActiveFilters, accountOptions, accountOptionsResponseLoading, accountFilterOpen } =
        useValues(logic)
    const { setFilters, setSearch, setAccountFilter, setAccountFilterOpen, loadAccountOptions, resetFilters } =
        useActions(logic)
    const status: LemonMenuItems = [
        {
            items: CUSTOMER_TASK_STATUS_OPTIONS.map((o) => ({
                label: o.label,
                active: filters.status === o.value,
                onClick: () => setFilters({ status: o.value }),
            })),
        },
    ]
    const archive: LemonMenuItems = [
        {
            items: CUSTOMER_TASK_ARCHIVE_OPTIONS.map((o) => ({
                label: o.label,
                active: filters.archiveState === o.value,
                onClick: () => setFilters({ archiveState: o.value }),
            })),
        },
    ]
    const due: LemonMenuItems = [
        {
            items: CUSTOMER_TASK_DUE_OPTIONS.map((o) => ({
                label: o.label,
                active: filters.due === o.value,
                onClick: () => setFilters({ due: o.value }),
            })),
        },
    ]
    const assignee: LemonMenuItems = [
        {
            items: [
                { label: 'Anyone', active: filters.assignee === 'any', onClick: () => setFilters({ assignee: 'any' }) },
                { label: 'Me', active: filters.assignee === 'me', onClick: () => setFilters({ assignee: 'me' }) },
                ...(canViewAll
                    ? [
                          {
                              label: 'Unassigned',
                              active: filters.assignee === 'unassigned',
                              onClick: () => setFilters({ assignee: 'unassigned' }),
                          },
                      ]
                    : []),
            ],
        },
    ]
    const options = accountOptions.map((a) => ({ key: a.id, label: a.name }))
    if (filters.account && !options.some((o) => o.key === filters.account?.id)) {
        options.unshift({ key: filters.account.id, label: filters.account.name })
    }
    return (
        <div className="flex flex-wrap items-center gap-2" data-attr="customer-tasks-filters">
            <LemonInput
                type="search"
                value={filters.search}
                onChange={setSearch}
                placeholder="Search tasks"
                size="small"
                className="min-w-64"
                data-attr="customer-tasks-search"
            />
            <LemonMenu items={status}>
                <LemonButton type="secondary" size="small" icon={<IconFilter />} sideIcon={<IconChevronDown />}>
                    {CUSTOMER_TASK_STATUS_OPTIONS.find((o) => o.value === filters.status)?.label}
                </LemonButton>
            </LemonMenu>
            {canViewAll && (
                <LemonMenu items={assignee}>
                    <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                        {assigneeLabel(filters.assignee)}
                    </LemonButton>
                </LemonMenu>
            )}
            {canViewAll && (
                <MemberSelect
                    value={typeof filters.assignee === 'number' ? filters.assignee : null}
                    defaultLabel="Choose member"
                    type="secondary"
                    size="small"
                    onChange={(u) => setFilters({ assignee: u?.id ?? 'any' })}
                />
            )}{' '}
            {context === 'inbox' && (
                <LemonMenu items={due}>
                    <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                        {CUSTOMER_TASK_DUE_OPTIONS.find((o) => o.value === filters.due)?.label}
                    </LemonButton>
                </LemonMenu>
            )}
            {context === 'inbox' && (
                <LemonDropdown
                    visible={accountFilterOpen}
                    onVisibilityChange={setAccountFilterOpen}
                    closeOnClickInside={false}
                    placement="bottom-start"
                    overlay={
                        <div className="p-2 min-w-64">
                            <LemonInputSelect
                                mode="single"
                                value={filters.account ? [filters.account.id] : []}
                                options={options}
                                loading={accountOptionsResponseLoading}
                                onInputChange={(query) => loadAccountOptions({ query })}
                                onChange={(values) => {
                                    const id = values[0]
                                    const account = accountOptions.find((a) => a.id === id)
                                    setAccountFilter(account ? { id: account.id, name: account.name } : null)
                                    setAccountFilterOpen(false)
                                }}
                                placeholder="Search accounts"
                            />
                        </div>
                    }
                >
                    <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                        {filters.account?.name ?? 'Account'}
                    </LemonButton>
                </LemonDropdown>
            )}
            <LemonMenu items={archive}>
                <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                    {CUSTOMER_TASK_ARCHIVE_OPTIONS.find((o) => o.value === filters.archiveState)?.label}
                </LemonButton>
            </LemonMenu>
            {hasActiveFilters && (
                <LemonButton type="tertiary" size="small" icon={<IconX />} onClick={resetFilters}>
                    Reset filters
                </LemonButton>
            )}
        </div>
    )
}
function assigneeLabel(value: CustomerTaskAssigneeFilter): string {
    return value === 'any' ? 'Anyone' : value === 'me' ? 'Me' : value === 'unassigned' ? 'Unassigned' : 'Member'
}
