import { useActions, useValues } from 'kea'
import { useId, useState } from 'react'

import {
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    useComboboxAnchor,
} from '@posthog/quill'

import { roleAccessControlLogic } from '../roleAccessControlLogic'

// Marks the list item that creates a role from the typed name, so it never reads as an existing role's id
const CREATE_ROLE_PREFIX = 'create-role:'

export function QuillMemberRolesPicker({ userUuid }: { userUuid: string }): JSX.Element {
    const { sortedRoles, rolesLoading, canEditRoles } = useValues(roleAccessControlLogic)
    const { addMembersToRole, removeMemberFromRole, createRoleWithMember } = useActions(roleAccessControlLogic)
    const [search, setSearch] = useState('')
    const anchor = useComboboxAnchor()
    const inputId = useId()

    // `user_uuid` on role members is write-only in the API, so the readable id is `member.user.uuid`
    const currentRoles = sortedRoles.filter((role) => role.members.some((member) => member.user.uuid === userUuid))
    const rolesById = Object.fromEntries(sortedRoles.map((role) => [role.id, role]))

    const newRoleName = search.trim()
    const canCreate =
        newRoleName.length > 0 && !sortedRoles.some((role) => role.name.toLowerCase() === newRoleName.toLowerCase())
    const items = [...sortedRoles.map((role) => role.id), ...(canCreate ? [`${CREATE_ROLE_PREFIX}${newRoleName}`] : [])]

    const labelOf = (value: string): string =>
        value.startsWith(CREATE_ROLE_PREFIX)
            ? `Create role "${value.slice(CREATE_ROLE_PREFIX.length)}"`
            : (rolesById[value]?.name ?? value)

    const onValueChange = (next: string[]): void => {
        const nextIds = new Set(next)
        for (const value of next) {
            if (value.startsWith(CREATE_ROLE_PREFIX)) {
                createRoleWithMember(value.slice(CREATE_ROLE_PREFIX.length), userUuid)
                setSearch('')
                continue
            }
            const role = rolesById[value]
            if (role && !currentRoles.includes(role)) {
                addMembersToRole(role, [userUuid])
            }
        }
        for (const role of currentRoles) {
            if (nextIds.has(role.id)) {
                continue
            }
            const roleMember = role.members.find((member) => member.user.uuid === userUuid)
            if (roleMember) {
                removeMemberFromRole(role, roleMember.id)
            }
        }
    }

    const disabledReason = canEditRoles === false ? 'You cannot edit roles' : rolesLoading ? 'Saving roles…' : undefined

    return (
        <Combobox<string, true>
            multiple
            autoHighlight
            items={items}
            itemToStringLabel={labelOf}
            value={currentRoles.map((role) => role.id)}
            onValueChange={(next: string[], eventDetails) => {
                // Escape with the list closed would otherwise clear every role
                if (eventDetails.reason === 'escape-key') {
                    eventDetails.allowPropagation()
                    return
                }
                onValueChange(next ?? [])
            }}
            inputValue={search}
            onInputValueChange={setSearch}
        >
            <ComboboxChips ref={anchor} disabledReason={disabledReason} data-attr="member-access-roles">
                <ComboboxValue>
                    {(values: string[]) => (
                        <>
                            {values.map((roleId) => (
                                <ComboboxChip key={roleId}>{labelOf(roleId)}</ComboboxChip>
                            ))}
                            <ComboboxChipsInput
                                id={inputId}
                                aria-label="Roles"
                                placeholder={values.length ? '' : 'Add roles…'}
                            />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>Type a name to create a role</ComboboxEmpty>
                <ComboboxList>
                    {(value: string) => (
                        <ComboboxItem key={value} value={value}>
                            {labelOf(value)}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
