import { useActions, useValues } from 'kea'

import { IconPlusSmall, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { outOfOfficeLogic } from '../OutOfOffice/outOfOfficeLogic'
import { AssigneeIconDisplay, AssigneeLabelDisplay } from './AssigneeDisplay'
import { assigneeSelectLogic } from './assigneeSelectLogic'
import { Assignee, TicketAssignee, toTicketAssignee } from './types'

export interface AssigneeDropdownProps {
    assignee: TicketAssignee
    onChange: (assignee: TicketAssignee) => void
}

export function AssigneeDropdown({ assignee, onChange }: AssigneeDropdownProps): JSX.Element {
    const { search, filteredRoles, otherFilteredMembers, currentUserMember, rolesLoading, membersLoading } =
        useValues(assigneeSelectLogic)
    const { setSearch } = useActions(assigneeSelectLogic)
    const { awayUserIds } = useValues(outOfOfficeLogic)

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

                {currentUserMember && (
                    <li>
                        <AssigneeItem
                            item={{
                                id: currentUserMember.user.id,
                                type: 'user',
                                user: currentUserMember.user,
                            }}
                            onSelect={onChange}
                            activeId={assignee?.id}
                            labelSuffix={
                                <>
                                    <span className="text-secondary">(you)</span>
                                    {awayUserIds.has(currentUserMember.user.id) && <AwayTag />}
                                </>
                            }
                        />
                    </li>
                )}

                <Section
                    title="Roles"
                    loading={rolesLoading}
                    search={!!search}
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

                {(!!search || membersLoading || otherFilteredMembers.length > 0) && (
                    <Section
                        title="Users"
                        loading={membersLoading}
                        search={!!search}
                        items={otherFilteredMembers.map((member) => ({
                            id: member.user.id,
                            type: 'user' as const,
                            user: member.user,
                        }))}
                        onSelect={onChange}
                        activeId={assignee?.id}
                        awayUserIds={awayUserIds}
                    />
                )}
            </ul>
        </div>
    )
}

const AwayTag = (): JSX.Element => (
    <LemonTag size="small" type="caution">
        Away
    </LemonTag>
)

const AssigneeItem = ({
    item,
    onSelect,
    activeId,
    labelSuffix,
}: {
    item: Assignee
    onSelect: (value: TicketAssignee) => void
    activeId?: string | number
    labelSuffix?: JSX.Element
}): JSX.Element => {
    return (
        <LemonButton
            fullWidth
            role="menuitem"
            size="small"
            icon={<AssigneeIconDisplay assignee={item} />}
            onClick={() => item?.id && onSelect(String(activeId) === String(item.id) ? null : toTicketAssignee(item))}
            active={String(activeId) === String(item?.id)}
        >
            <span className="flex items-center gap-1">
                <AssigneeLabelDisplay assignee={item} />
                {labelSuffix}
            </span>
        </LemonButton>
    )
}

const Section = ({
    loading,
    search,
    items,
    onSelect,
    activeId,
    emptyState,
    title,
    awayUserIds,
}: {
    title: string
    loading: boolean
    search: boolean
    items: Assignee[]
    onSelect: (value: TicketAssignee) => void
    activeId?: string | number
    emptyState?: JSX.Element
    awayUserIds?: Set<number>
}): JSX.Element => {
    return (
        <li>
            <section className="deprecated-space-y-px">
                <h5 className="mx-2 my-0.5">{title}</h5>
                {items.map((item) => (
                    <li key={item?.id || 'unassigned'}>
                        <AssigneeItem
                            item={item}
                            onSelect={onSelect}
                            activeId={activeId}
                            labelSuffix={
                                item?.type === 'user' && awayUserIds?.has(item.user.id) ? <AwayTag /> : undefined
                            }
                        />
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
