import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { useId, useMemo, useState } from 'react'

import {
    Button,
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    DataTable,
    Text,
    useComboboxAnchor,
} from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { fullName } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, OrganizationMemberType, RoleMemberType } from '~/types'

import { roleAccessControlLogic } from '../roleAccessControlLogic'
import { openRoleAccessSettings } from '../roleActions'

// The same cap as the LemonUI member picker.
const MAX_PICKER_RESULTS = 100

function MemberPicker({
    id,
    membersByUuid,
    disabledReason,
}: {
    id: string
    membersByUuid: Record<string, OrganizationMemberType>
    disabledReason?: string
}): JSX.Element {
    const anchor = useComboboxAnchor()

    return (
        <>
            <ComboboxChips ref={anchor} disabledReason={disabledReason}>
                <ComboboxValue>
                    {(values: string[]) => (
                        <>
                            {values.map((uuid) => (
                                <ComboboxChip key={uuid}>
                                    <span className="ph-no-capture">
                                        {fullName(membersByUuid[uuid]?.user) || membersByUuid[uuid]?.user.email}
                                    </span>
                                </ComboboxChip>
                            ))}
                            <ComboboxChipsInput
                                id={id}
                                aria-label="Search for members to add"
                                placeholder={values.length ? '' : 'Search for members to add...'}
                            />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>No matches</ComboboxEmpty>
                <ComboboxList>
                    {(uuid: string) => {
                        const member = membersByUuid[uuid]
                        return (
                            <ComboboxItem key={uuid} value={uuid}>
                                <span className="ph-no-capture flex min-w-0 items-center gap-2">
                                    <QuillPersonAvatar
                                        name={fullName(member?.user)}
                                        email={member?.user.email}
                                        size="xs"
                                    />
                                    <span className="truncate">{fullName(member?.user)}</span>
                                    <Text size="xs" variant="muted" render={<span className="truncate" />}>
                                        {member?.user.email}
                                    </Text>
                                </span>
                            </ComboboxItem>
                        )
                    }}
                </ComboboxList>
            </ComboboxContent>
        </>
    )
}

export function QuillRoleDetails({ roleId }: { roleId: string }): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { sortedMembers, roles, canEditRoles } = useValues(roleAccessControlLogic)
    const { addMembersToRole, removeMemberFromRole } = useActions(roleAccessControlLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const [membersToAdd, setMembersToAdd] = useState<string[]>([])
    const pickerId = useId()

    const role = roles?.find((role) => role.id === roleId)

    const membersNotInRole = useMemo(() => {
        const membersInRole = new Set(role?.members.map((member) => member.user.uuid))
        return sortedMembers?.filter((member) => !membersInRole.has(member.user.uuid)) ?? []
    }, [role?.members, sortedMembers])

    const membersByUuid = useMemo(
        () => Object.fromEntries(membersNotInRole.map((member) => [member.user.uuid, member])),
        [membersNotInRole]
    )

    if (!role) {
        return null
    }

    const onSubmit = (): void => {
        addMembersToRole(role, membersToAdd)
        setMembersToAdd([])
    }

    const editReason = !canEditRoles ? 'You cannot edit this' : undefined

    const columns: ColumnDef<RoleMemberType>[] = [
        {
            id: 'user_profile_picture',
            header: '',
            enableSorting: false,
            cell: ({ row }) => <QuillPersonAvatar name={fullName(row.original.user)} email={row.original.user.email} />,
        },
        {
            id: 'user_name',
            header: 'Name',
            meta: { expand: true },
            accessorFn: (member) => fullName(member.user),
            sortingFn: (a, b) => fullName(a.original.user).localeCompare(fullName(b.original.user)),
            cell: ({ row }) => (
                <Text size="xs" render={<span />} className="m-0 ph-no-capture">
                    {row.original.user.uuid == user?.uuid
                        ? `${fullName(row.original.user)} (you)`
                        : fullName(row.original.user)}
                </Text>
            ),
        },
        {
            id: 'user_email',
            header: 'Email',
            accessorFn: (member) => member.user.email,
            sortingFn: (a, b) => a.original.user.email.localeCompare(b.original.user.email),
            cell: ({ row }) => (
                <Text size="xs" render={<span />} className="m-0 ph-no-capture">
                    {row.original.user.email}
                </Text>
            ),
        },
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row }) => (
                <Button
                    variant="destructive-outline"
                    disabledReason={editReason}
                    onClick={() => removeMemberFromRole(role, row.original.id)}
                >
                    Remove
                </Button>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <div className="min-w-64">
                        <Combobox<string, true>
                            multiple
                            autoHighlight
                            items={membersNotInRole.map((member) => member.user.uuid)}
                            limit={MAX_PICKER_RESULTS}
                            itemToStringLabel={(uuid: string) =>
                                `${fullName(membersByUuid[uuid]?.user)} ${membersByUuid[uuid]?.user.email ?? ''}`
                            }
                            value={membersToAdd}
                            onValueChange={(next: string[], eventDetails) => {
                                // Escape with the list closed would otherwise clear every selection.
                                if (eventDetails.reason === 'escape-key') {
                                    eventDetails.allowPropagation()
                                    return
                                }
                                setMembersToAdd(next ?? [])
                            }}
                        >
                            <MemberPicker id={pickerId} membersByUuid={membersByUuid} disabledReason={editReason} />
                        </Combobox>
                    </div>

                    <Button
                        variant="primary"
                        onClick={onSubmit}
                        disabledReason={
                            editReason ?? (!membersToAdd.length ? 'Please select members to add' : undefined)
                        }
                    >
                        Add members
                    </Button>
                </div>
                <Button
                    variant="outline"
                    onClick={() =>
                        guardAvailableFeature(AvailableFeature.ROLE_BASED_ACCESS, () => openRoleAccessSettings(role.id))
                    }
                >
                    Manage access
                </Button>
            </div>

            <DataTable columns={columns} data={role.members} fullWidth getRowId={(member) => member.id} />
        </div>
    )
}
