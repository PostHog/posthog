import { useActions, useValues } from 'kea'

import { IconPlusSmall, IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { AssigneeIconDisplay, AssigneeLabelDisplay } from './AssigneeDisplay'
import { assigneeSelectLogic } from './assigneeSelectLogic'
import { Assignee, TicketAssignee } from './types'

export interface AssigneeDropdownProps {
    assignee: TicketAssignee
    onChange: (assignee: TicketAssignee) => void
}

export function AssigneeDropdown({ assignee, onChange }: AssigneeDropdownProps): JSX.Element {
    const { search, filteredRoles, filteredMembers, rolesLoading, membersLoading } = useValues(assigneeSelectLogic)
    const { setSearch } = useActions(assigneeSelectLogic)

    return (
        <div className="max-w-100 deprecated-space-y-2">
            <LemonInput type="search" placeholder="Search" autoFocus value={search} onChange={setSearch} fullWidth />
            <ul className="deprecated-space-y-2">
                {assignee && (
                    <li>
                        <LemonButton
                            fullWidth
                            role="menuitem"
                            size="small"
                            icon={<IconX />}
                            onClick={() => onChange(null)}
                        >
                            Remove assignee
                        </LemonButton>
                    </li>
                )}

                <Section
                    title="Roles"
                    loading={rolesLoading}
                    search={!!search}
                    type="role"
                    items={filteredRoles.map((role) => ({
                        id: role.id,
                        type: 'role' as const,
                        role: role,
                    }))}
                    onSelect={onChange}
                    activeId={assignee?.id}
                    emptyState={
                        <LemonButton
                            fullWidth
                            size="small"
                            icon={<IconPlusSmall />}
                            to={urls.settings('organization-roles')}
                        >
                            <div className="text-secondary">Create role</div>
                        </LemonButton>
                    }
                />

                <Section
                    title="Users"
                    loading={membersLoading}
                    search={!!search}
                    type="user"
                    items={filteredMembers.map((member) => ({
                        id: member.user.id,
                        type: 'user' as const,
                        user: member.user,
                    }))}
                    onSelect={onChange}
                    activeId={assignee?.id}
                />
            </ul>
        </div>
    )
}

const Section = ({
    loading,
    search,
    type,
    items,
    onSelect,
    activeId,
    emptyState,
    title,
}: {
    title: string
    loading: boolean
    search: boolean
    type: 'user' | 'role'
    items: Assignee[]
    onSelect: (value: TicketAssignee) => void
    activeId?: string | number
    emptyState?: JSX.Element
}): JSX.Element => {
    return (
        <li>
            <section className="deprecated-space-y-px">
                <h5 className="mx-2 my-0.5">{title}</h5>
                {items.map((item) => (
                    <li key={item?.id || 'unassigned'}>
                        <LemonButton
                            fullWidth
                            role="menuitem"
                            size="small"
                            icon={<AssigneeIconDisplay assignee={item} />}
                            onClick={() =>
                                item?.id &&
                                onSelect(String(activeId) === String(item.id) ? null : { type, id: item.id })
                            }
                            active={String(activeId) === String(item?.id)}
                        >
                            <AssigneeLabelDisplay assignee={item} />
                        </LemonButton>
                    </li>
                ))}

                {loading ? (
                    <div className="p-2 text-secondary italic truncate border-t">Loading...</div>
                ) : items.length === 0 ? (
                    search ? (
                        <div className="p-2 text-secondary italic truncate border-t">
                            <span>No matches</span>
                        </div>
                    ) : (
                        <div className="border-t pt-1">{emptyState}</div>
                    )
                ) : null}
            </section>
        </li>
    )
}
