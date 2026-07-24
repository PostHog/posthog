import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { clearFilterButtonProps } from '../clearFilterButtonProps'
import { AssigneeIconDisplay, AssigneeLabelDisplay, AssigneeResolver } from './AssigneeDisplay'
import { assigneeSelectLogic } from './assigneeSelectLogic'
import { Assignee, AssigneeFilterEntry, MAX_ASSIGNEE_FILTER_ENTRIES } from './types'

function isSameEntry(a: AssigneeFilterEntry, b: AssigneeFilterEntry): boolean {
    if (a === 'unassigned' || b === 'unassigned') {
        return a === b
    }
    return a.type === b.type && String(a.id) === String(b.id)
}

export function AssigneeMultiSelect({
    value,
    onChange,
}: {
    value: AssigneeFilterEntry[]
    onChange: (value: AssigneeFilterEntry[]) => void
}): JSX.Element {
    const { search, filteredRoles, otherFilteredMembers, currentUserMember, rolesLoading, membersLoading } =
        useValues(assigneeSelectLogic)
    const { setSearch, ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)
    const [showPopover, setShowPopover] = useState(false)

    useEffect(() => {
        ensureAssigneeTypesLoaded()
    }, [ensureAssigneeTypesLoaded])

    const isSelected = (entry: AssigneeFilterEntry): boolean => value.some((selected) => isSameEntry(selected, entry))
    const toggleEntry = (entry: AssigneeFilterEntry): void => {
        onChange(isSelected(entry) ? value.filter((selected) => !isSameEntry(selected, entry)) : [...value, entry])
    }
    const selectionCapReason =
        value.length >= MAX_ASSIGNEE_FILTER_ENTRIES
            ? `You can select up to ${MAX_ASSIGNEE_FILTER_ENTRIES} assignees`
            : undefined

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            onVisibilityChange={(visible) => {
                setShowPopover(visible)
                if (!visible) {
                    setSearch('')
                }
            }}
            overlay={
                <div className="max-w-100 deprecated-space-y-2">
                    <LemonInput
                        type="search"
                        placeholder="Search"
                        autoFocus
                        value={search}
                        onChange={setSearch}
                        fullWidth
                    />
                    <ul className="deprecated-space-y-2">
                        <li>
                            <LemonButton
                                fullWidth
                                role="menuitem"
                                size="small"
                                icon={
                                    <LemonCheckbox checked={isSelected('unassigned')} className="pointer-events-none" />
                                }
                                disabledReason={isSelected('unassigned') ? undefined : selectionCapReason}
                                onClick={() => toggleEntry('unassigned')}
                            >
                                <span className="flex items-center gap-1">
                                    <AssigneeIconDisplay assignee={null} size="small" />
                                    Unassigned
                                </span>
                            </LemonButton>
                        </li>
                        {currentUserMember && (
                            <li>
                                <AssigneeFilterItem
                                    item={{
                                        id: currentUserMember.user.id,
                                        type: 'user',
                                        user: currentUserMember.user,
                                    }}
                                    isSelected={isSelected}
                                    onToggle={toggleEntry}
                                    selectionCapReason={selectionCapReason}
                                    labelSuffix={<span className="text-secondary">(you)</span>}
                                />
                            </li>
                        )}
                        <Section
                            title="Roles"
                            loading={rolesLoading}
                            search={!!search}
                            items={filteredRoles.map((role) => ({ id: role.id, type: 'role' as const, role }))}
                            isSelected={isSelected}
                            onToggle={toggleEntry}
                            selectionCapReason={selectionCapReason}
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
                                isSelected={isSelected}
                                onToggle={toggleEntry}
                                selectionCapReason={selectionCapReason}
                            />
                        )}
                    </ul>
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                active={showPopover}
                {...clearFilterButtonProps(value.length > 0 ? () => onChange([]) : null, 'Clear assignee filter')}
            >
                <TriggerLabel value={value} />
            </LemonButton>
        </LemonDropdown>
    )
}

function TriggerLabel({ value }: { value: AssigneeFilterEntry[] }): JSX.Element {
    if (value.length === 0) {
        return <>All assignees</>
    }
    if (value.length > 1) {
        return <>{value.length} assignees</>
    }
    const entry = value[0]
    if (entry === 'unassigned') {
        return (
            <span className="flex items-center gap-1">
                <AssigneeIconDisplay assignee={null} size="small" />
                <AssigneeLabelDisplay assignee={null} size="small" />
            </span>
        )
    }
    return (
        <AssigneeResolver assignee={entry}>
            {({ assignee }) => (
                <span className="flex items-center gap-1">
                    <AssigneeIconDisplay assignee={assignee} size="small" />
                    <AssigneeLabelDisplay assignee={assignee} size="small" placeholder="1 assignee" />
                </span>
            )}
        </AssigneeResolver>
    )
}

const AssigneeFilterItem = ({
    item,
    isSelected,
    onToggle,
    selectionCapReason,
    labelSuffix,
}: {
    item: NonNullable<Assignee>
    isSelected: (entry: AssigneeFilterEntry) => boolean
    onToggle: (entry: AssigneeFilterEntry) => void
    selectionCapReason?: string
    labelSuffix?: JSX.Element
}): JSX.Element => {
    return (
        <LemonButton
            fullWidth
            role="menuitem"
            size="small"
            icon={<LemonCheckbox checked={isSelected(item)} className="pointer-events-none" />}
            disabledReason={isSelected(item) ? undefined : selectionCapReason}
            onClick={() => onToggle({ type: item.type, id: item.id })}
        >
            <span className="flex items-center gap-1">
                <AssigneeIconDisplay assignee={item} size="small" />
                <AssigneeLabelDisplay assignee={item} />
                {labelSuffix}
            </span>
        </LemonButton>
    )
}

const Section = ({
    title,
    loading,
    search,
    items,
    isSelected,
    onToggle,
    selectionCapReason,
    emptyState,
}: {
    title: string
    loading: boolean
    search: boolean
    items: NonNullable<Assignee>[]
    isSelected: (entry: AssigneeFilterEntry) => boolean
    onToggle: (entry: AssigneeFilterEntry) => void
    selectionCapReason?: string
    emptyState?: JSX.Element
}): JSX.Element => {
    return (
        <li>
            <section className="deprecated-space-y-px">
                <h5 className="mx-2 my-0.5">{title}</h5>
                {items.map((item) => (
                    <li key={item.id}>
                        <AssigneeFilterItem
                            item={item}
                            isSelected={isSelected}
                            onToggle={onToggle}
                            selectionCapReason={selectionCapReason}
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
