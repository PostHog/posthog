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

import { organizationLogic } from 'scenes/organizationLogic'

import { RoleType } from '~/types'

import { roleAccessControlLogic } from '../roleAccessControlLogic'

type RoleChoice = { kind: 'role'; id: string; name: string } | { kind: 'new'; name: string }

const choiceKey = (choice: RoleChoice): string => (choice.kind === 'role' ? choice.id : `new:${choice.name}`)
const choiceLabel = (choice: RoleChoice): string =>
    choice.kind === 'role' ? choice.name : `Create role "${choice.name}"`

// The anchor comes from the Combobox's own context, so these parts have to render inside it
function RolesPickerFields({ disabledReason }: { disabledReason: string | undefined }): JSX.Element {
    const anchor = useComboboxAnchor()
    const inputId = useId()

    return (
        <>
            <ComboboxChips ref={anchor} disabledReason={disabledReason} data-attr="member-access-roles">
                <ComboboxValue>
                    {(values: RoleChoice[]) => (
                        <>
                            {values.map((choice) => (
                                <ComboboxChip key={choiceKey(choice)}>{choiceLabel(choice)}</ComboboxChip>
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
                    {(choice: RoleChoice) => (
                        <ComboboxItem key={choiceKey(choice)} value={choice}>
                            {choiceLabel(choice)}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </>
    )
}

export function QuillMemberRolesPicker({ userUuid }: { userUuid: string }): JSX.Element {
    const { sortedRoles, rolesLoading } = useValues(roleAccessControlLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)
    const { setMemberRoles } = useActions(roleAccessControlLogic)
    const [search, setSearch] = useState('')

    const toChoice = (role: RoleType): RoleChoice => ({ kind: 'role', id: role.id, name: role.name })
    const roleChoices = sortedRoles.map(toChoice)
    const currentChoices = sortedRoles
        .filter((role) => role.members.some((member) => member.user.uuid === userUuid))
        .map(toChoice)
    const newRoleName = search.trim()
    const canCreate =
        newRoleName.length > 0 && !sortedRoles.some((role) => role.name.toLowerCase() === newRoleName.toLowerCase())
    const items: RoleChoice[] = canCreate ? [...roleChoices, { kind: 'new', name: newRoleName }] : roleChoices

    // Roles belong to the organization, so the gate is organization admin, not project access. Unknown counts as no.
    const disabledReason = !isAdminOrOwner
        ? 'Only organization admins can change roles'
        : rolesLoading
          ? 'Saving roles…'
          : undefined

    return (
        <Combobox<RoleChoice, true>
            multiple
            // The chips only grey out; the open list would still accept a second click on a role that is saving
            disabled={!!disabledReason}
            autoHighlight
            items={items}
            itemToStringLabel={choiceLabel}
            isItemEqualToValue={(item, value) => choiceKey(item) === choiceKey(value)}
            value={currentChoices}
            onValueChange={(next: RoleChoice[], eventDetails) => {
                // Escape with the list closed would otherwise clear every role
                if (eventDetails.reason === 'escape-key') {
                    eventDetails.allowPropagation()
                    return
                }
                const roleIds = next.flatMap((choice) => (choice.kind === 'role' ? [choice.id] : []))
                const newRoleNames = next.flatMap((choice) => (choice.kind === 'new' ? [choice.name] : []))
                setMemberRoles(userUuid, roleIds, newRoleNames)
                if (newRoleNames.length) {
                    setSearch('')
                }
            }}
            inputValue={search}
            onInputValueChange={setSearch}
        >
            <RolesPickerFields disabledReason={disabledReason} />
        </Combobox>
    )
}
