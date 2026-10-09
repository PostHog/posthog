import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput, ProfilePicture } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { fullName } from 'lib/utils/strings'

import type { RoleType } from '~/types'

import { isRoleAssigneeFilter, type CustomerTaskAssigneeFilter } from './customerTaskFilters'
import { customerTasksAssigneeDropdownLogic } from './customerTasksAssigneeDropdownLogic'

export interface CustomerTasksAssigneeDropdownProps {
    value: CustomerTaskAssigneeFilter
    onChange: (value: CustomerTaskAssigneeFilter) => void
}

export function CustomerTasksAssigneeDropdown({ value, onChange }: CustomerTasksAssigneeDropdownProps): JSX.Element {
    const {
        search,
        rolesLoading,
        quickOptions,
        myRoles,
        otherRoles,
        filteredMembers,
        membersLoading,
        nothingMatches,
        assigneeLabel,
    } = useValues(customerTasksAssigneeDropdownLogic)
    const { setSearch, ensureAllMembersLoaded } = useActions(customerTasksAssigneeDropdownLogic)
    const [open, setOpen] = useState(false)
    // The trigger label names the selected member, so the member list has to load before the dropdown opens.
    useOnMountEffect(ensureAllMembersLoaded)

    const select = (next: CustomerTaskAssigneeFilter): void => {
        setOpen(false)
        setSearch('')
        onChange(next)
    }

    const selectedRoleId = isRoleAssigneeFilter(value) ? value.roleId : null

    const renderRole = (role: RoleType): JSX.Element => (
        <LemonButton
            key={role.id}
            fullWidth
            role="menuitem"
            size="small"
            active={selectedRoleId === role.id}
            icon={<ProfilePicture user={{ first_name: role.name }} size="sm" />}
            onClick={() => select({ roleId: role.id })}
            data-attr="customer-tasks-assignee-filter-role"
        >
            <span className="truncate">{role.name}</span>
        </LemonButton>
    )

    return (
        <LemonDropdown
            visible={open}
            onVisibilityChange={(visible) => {
                setOpen(visible)
                if (!visible) {
                    setSearch('')
                }
            }}
            closeOnClickInside={false}
            placement="bottom-start"
            overlay={
                <div className="flex flex-col gap-1 p-1 w-72 max-h-120 overflow-y-auto">
                    <LemonInput
                        type="search"
                        placeholder="Search roles and members"
                        autoFocus
                        size="small"
                        value={search}
                        onChange={setSearch}
                        fullWidth
                    />
                    {quickOptions.map((option) => (
                        <LemonButton
                            key={option.value}
                            fullWidth
                            role="menuitem"
                            size="small"
                            active={value === option.value}
                            onClick={() => select(option.value)}
                        >
                            {option.label}
                        </LemonButton>
                    ))}
                    {myRoles.length > 0 && (
                        <section className="flex flex-col">
                            <h5 className="mx-2 my-1">My roles</h5>
                            {myRoles.map(renderRole)}
                        </section>
                    )}
                    {rolesLoading ? (
                        <div className="px-2 py-1 text-secondary">Loading roles…</div>
                    ) : (
                        otherRoles.length > 0 && (
                            <section className="flex flex-col">
                                <h5 className="mx-2 my-1">{myRoles.length > 0 ? 'Other roles' : 'Roles'}</h5>
                                {otherRoles.map(renderRole)}
                            </section>
                        )
                    )}
                    {membersLoading ? (
                        <div className="px-2 py-1 text-secondary">Loading members…</div>
                    ) : (
                        filteredMembers.length > 0 && (
                            <section className="flex flex-col">
                                <h5 className="mx-2 my-1">Members</h5>
                                {filteredMembers.map((member) => (
                                    <LemonButton
                                        key={member.user.id}
                                        fullWidth
                                        role="menuitem"
                                        size="small"
                                        active={value === member.user.id}
                                        icon={<ProfilePicture user={member.user} size="sm" />}
                                        onClick={() => select(member.user.id)}
                                        data-attr="customer-tasks-assignee-filter-member"
                                    >
                                        <span className="truncate">{fullName(member.user) || member.user.email}</span>
                                    </LemonButton>
                                ))}
                            </section>
                        )
                    )}
                    {nothingMatches && <div className="px-2 py-1 text-secondary">No roles or members match.</div>}
                </div>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                sideIcon={<IconChevronDown />}
                data-attr="customer-tasks-assignee-filter"
            >
                {assigneeLabel(value)}
            </LemonButton>
        </LemonDropdown>
    )
}
