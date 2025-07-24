import { IconPlus } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonTable,
    LemonTableColumns,
    ProfileBubbles,
    ProfilePicture,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { fullName } from 'lib/utils'
import { useMemo, useState } from 'react'
import { userLogic } from 'scenes/userLogic'

import { RoleType } from '~/types'

import { roleAccessControlLogic } from './roleAccessControlLogic'

export function RolesAccessControls(): JSX.Element {
    const { roles, rolesLoading, selectedRoleId } = useValues(roleAccessControlLogic)

    const { selectRoleId, setEditingRoleId } = useActions(roleAccessControlLogic)

    const columns: LemonTableColumns<RoleType> = [
        {
            title: 'Role',
            key: 'role',
            width: 0,
            render: (_, role) => (
                <span className="whitespace-nowrap">
                    <LemonTableLink
                        onClick={
                            role
                                ? () => (role.id === selectedRoleId ? selectRoleId(null) : selectRoleId(role.id))
                                : undefined
                        }
                        title={role?.name ?? 'Default'}
                    />
                </span>
            ),
        },
        {
            title: 'Members',
            key: 'members',
            render: (_, role) => {
                return role ? (
                    role.members.length ? (
                        <ProfileBubbles
                            people={
                                role?.members?.map((member) => ({
                                    email: member.user.email,
                                    name: fullName(member.user),
                                    title: `${fullName(member.user)} <${member.user.email}>`,
                                })) ?? []
                            }
                            onClick={() => (role.id === selectedRoleId ? selectRoleId(null) : selectRoleId(role.id))}
                        />
                    ) : (
                        'No members'
                    )
                ) : (
                    'All members'
                )
            },
        },
    ]

    return (
        <div className="deprecated-space-y-2">
            <p>
                Use roles to group your organization members and assign them permissions. Roles are currently used for
                access control but we will be expanding their uses in the future.
            </p>

            <div className="deprecated-space-y-2">
                <LemonTable
                    columns={columns}
                    dataSource={roles ?? []}
                    loading={rolesLoading}
                    expandable={{
                        isRowExpanded: (role) => !!selectedRoleId && role?.id === selectedRoleId,
                        onRowExpand: (role) => (role ? selectRoleId(role.id) : undefined),
                        onRowCollapse: () => selectRoleId(null),
                        expandedRowRender: (role) => (role ? <RoleDetails roleId={role?.id} /> : null),
                        rowExpandable: (role) => !!role,
                    }}
                />

                <LemonButton type="primary" onClick={() => setEditingRoleId('new')} icon={<IconPlus />}>
                    Add a role
                </LemonButton>
                <RoleModal />
            </div>
        </div>
    )
}

function RoleDetails({ roleId }: { roleId: string }): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { sortedMembers, roles, canEditRoles } = useValues(roleAccessControlLogic)
    const { addMembersToRole, removeMemberFromRole, setEditingRoleId } = useActions(roleAccessControlLogic)
    const [membersToAdd, setMembersToAdd] = useState<string[]>([])

    const role = roles?.find((role) => role.id === roleId)

    const onSubmit = membersToAdd.length
        ? () => {
              role && addMembersToRole(role, membersToAdd)
              setMembersToAdd([])
          }
        : undefined

    const membersNotInRole = useMemo(() => {
        const membersInRole = new Set(role?.members.map((member) => member.user.uuid))
        return sortedMembers?.filter((member) => !membersInRole.has(member.user.uuid)) ?? []
    }, [role?.members, sortedMembers])

    if (!role) {
        // This is mostly for typing
        return null
    }

    return (
        <div className="my-2 pr-2 deprecated-space-y-2">
            <div className="flex items-center gap-2 justify-between min-h-10">
                <div className="flex items-center gap-2">
                    <div className="min-w-[16rem]">
                        <LemonInputSelect
                            placeholder="Search for members to add..."
                            value={membersToAdd}
                            onChange={(newValues: string[]) => setMembersToAdd(newValues)}
                            mode="multiple"
                            disabled={!canEditRoles}
                            options={usersLemonSelectOptions(
                                membersNotInRole.map((member) => member.user),
                                'uuid'
                            )}
                        />
                    </div>

                    <LemonButton
                        type="primary"
                        onClick={onSubmit}
                        disabledReason={
                            !canEditRoles
                                ? 'You cannot edit this'
                                : !onSubmit
                                ? 'Please select members to add'
                                : undefined
                        }
                    >
                        Add members
                    </LemonButton>
                </div>
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={() => setEditingRoleId(role.id)}
                        disabledReason={!canEditRoles ? 'You cannot edit this' : undefined}
                    >
                        Edit
                    </LemonButton>
                </div>
            </div>

            <LemonTable
                columns={[
                    {
                        key: 'user_profile_picture',
                        render: function ProfilePictureRender(_, member) {
                            return <ProfilePicture user={member.user} />
                        },
                        width: 32,
                    },
                    {
                        title: 'Name',
                        key: 'user_name',
                        render: (_, member) =>
                            member.user.uuid == user?.uuid ? `${fullName(member.user)} (you)` : fullName(member.user),
                        sorter: (a, b) => fullName(a.user).localeCompare(fullName(b.user)),
                    },
                    {
                        title: 'Email',
                        key: 'user_email',
                        render: (_, member) => {
                            return <>{member.user.email}</>
                        },
                        sorter: (a, b) => a.user.email.localeCompare(b.user.email),
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, member) => {
                            return (
                                <div className="flex items-center gap-2">
                                    <LemonButton
                                        status="danger"
                                        size="small"
                                        type="tertiary"
                                        disabledReason={!canEditRoles ? 'You cannot edit this' : undefined}
                                        onClick={() => removeMemberFromRole(role, member.id)}
                                    >
                                        Remove
                                    </LemonButton>
                                </div>
                            )
                        },
                    },
                ]}
                dataSource={role.members}
            />
        </div>
    )
}

function RoleModal(): JSX.Element {
    const { editingRoleId } = useValues(roleAccessControlLogic)
    const { setEditingRoleId, submitEditingRole, deleteRole } = useActions(roleAccessControlLogic)
    const isEditing = editingRoleId !== 'new'

    const onDelete = (): void => {
        LemonDialog.open({
            title: 'Delete role',
            content: 'Are you sure you want to delete this role? This action cannot be undone.',
            primaryButton: {
                children: 'Delete permanently',
                onClick: () => deleteRole(editingRoleId as string),
                status: 'danger',
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return (
        <Form logic={roleAccessControlLogic} formKey="editingRole" enableFormOnSubmit>
            <LemonModal
                isOpen={!!editingRoleId}
                onClose={() => setEditingRoleId(null)}
                title={!isEditing ? 'Create' : `Edit`}
                footer={
                    <>
                        <div className="flex-1">
                            {isEditing ? (
                                <LemonButton type="secondary" status="danger" onClick={() => onDelete()}>
                                    Delete
                                </LemonButton>
                            ) : null}
                        </div>

                        <LemonButton type="secondary" onClick={() => setEditingRoleId(null)}>
                            Cancel
                        </LemonButton>

                        <LemonButton type="primary" htmlType="submit" onClick={submitEditingRole}>
                            {!isEditing ? 'Create' : 'Save'}
                        </LemonButton>
                    </>
                }
            >
                <LemonField label="Role name" name="name">
                    <LemonInput placeholder="Please enter a name..." autoFocus />
                </LemonField>
            </LemonModal>
        </Form>
    )
}
