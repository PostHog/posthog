import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonSelectMultiple,
    LemonTable,
    LemonTableColumns,
    ProfileBubbles,
    ProfilePicture,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter, Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { fullName } from 'lib/utils'
import { useMemo, useState } from 'react'
import { userLogic } from 'scenes/userLogic'

import { RoleType } from '~/types'

import { roleBasedAccessControlLogic, RoleWithResourceAccessControls } from './roleBasedAccessControlLogic'

export function RolesAndResourceAccessControls(): JSX.Element {
    const {
        rolesWithResourceAccessControls,
        rolesLoading,
        roleBasedAccessControlsLoading,
        resources,
        availableLevels,
        selectedRoleId,
    } = useValues(roleBasedAccessControlLogic)

    const { updateRoleBasedAccessControls, selectRoleId, setEditingRoleId } = useActions(roleBasedAccessControlLogic)

    const columns: LemonTableColumns<RoleWithResourceAccessControls> = [
        {
            title: 'Role',
            key: 'role',
            width: 0,
            render: (_, { role }) => (
                <span className="whitespace-nowrap">
                    <LemonTableLink
                        onClick={() => (role.id === selectedRoleId ? selectRoleId(null) : selectRoleId(role.id))}
                        title={role.name}
                    />
                </span>
            ),
        },
        {
            title: 'Members',
            key: 'members',
            render: (_, { role }) => {
                return role.members.length ? (
                    <ProfileBubbles
                        people={role.members.map((member) => ({
                            email: member.user.email,
                            name: member.user.first_name,
                            title: `${member.user.first_name} <${member.user.email}>`,
                        }))}
                        onClick={() => selectRoleId(role.id)}
                    />
                ) : (
                    'No members'
                )
            },
        },

        ...resources.map((resource) => ({
            title: resource,
            key: resource,
            width: 0,
            render: (_: any, { accessControlByResource, role }: RoleWithResourceAccessControls) => {
                const ac = accessControlByResource[resource]

                return (
                    <LemonSelect
                        size="small"
                        placeholder="No access"
                        className="my-1"
                        value={ac?.access_level}
                        onChange={(newValue) =>
                            updateRoleBasedAccessControls([
                                {
                                    resource,
                                    role: role.id,
                                    access_level: newValue,
                                },
                            ])
                        }
                        options={availableLevels.map((level) => ({
                            value: level,
                            label: capitalizeFirstLetter(level ?? ''),
                        }))}
                    />
                )
            },
        })),
    ]

    return (
        <div className="space-y-2">
            <LemonTable
                columns={columns}
                dataSource={rolesWithResourceAccessControls}
                loading={rolesLoading || roleBasedAccessControlsLoading}
                expandable={{
                    isRowExpanded: (record) => !!selectedRoleId && record.role.id === selectedRoleId,
                    onRowExpand: (record) => selectRoleId(record.role.id),
                    onRowCollapse: () => selectRoleId(null),
                    expandedRowRender: ({ role }) => <RoleDetails role={role} />,
                }}
            />

            <LemonButton type="primary" onClick={() => setEditingRoleId('new')}>
                Create role
            </LemonButton>
            <RoleModal />
        </div>
    )
}

function RoleDetails({ role }: { role: RoleType }): JSX.Element {
    const { user } = useValues(userLogic)
    const { sortedMembers } = useValues(roleBasedAccessControlLogic)
    const { addMembersToRole, removeMemberFromRole, setEditingRoleId } = useActions(roleBasedAccessControlLogic)
    const [membersToAdd, setMembersToAdd] = useState<string[]>([])
    const onSubmit = membersToAdd.length
        ? () => {
              addMembersToRole(role, membersToAdd)
              setMembersToAdd([])
          }
        : undefined

    const membersNotInRole = useMemo(() => {
        const membersInRole = new Set(role.members.map((member) => member.user.uuid))
        return sortedMembers?.filter((member) => !membersInRole.has(member.user.uuid)) ?? []
    }, [role.members, sortedMembers])

    return (
        <div className="my-2 pr-2 space-y-2">
            <div className="flex items-center gap-2 justify-between min-h-10">
                <div className="flex items-center gap-2">
                    <div className="min-w-[16rem]">
                        <LemonSelectMultiple
                            placeholder="Search for members to add..."
                            value={membersToAdd}
                            onChange={(newValues: string[]) => setMembersToAdd(newValues)}
                            filterOption={true}
                            mode="multiple"
                            options={membersNotInRole.map((member) => ({
                                key: member.user.uuid,
                                value: member.user.uuid,
                                label: fullName(member.user),
                            }))}
                        />
                    </div>

                    <LemonButton
                        type="primary"
                        onClick={onSubmit}
                        disabledReason={!onSubmit ? 'Please select members to add' : undefined}
                    >
                        Add members
                    </LemonButton>
                </div>
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" onClick={() => setEditingRoleId(role.id)}>
                        Edit role
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
                                        onClick={() => removeMemberFromRole(role, member.id)}
                                    >
                                        Remove
                                    </LemonButton>
                                </div>
                            )
                        },
                    },
                    /* {isAdminOrOwner && deleteMember && (
                                            <LemonButton
                                                icon={<IconTrash />}
                                                onClick={() => deleteMember(member.id)}
                                                tooltip="Remove user from role"
                                                type="tertiary"
                                                size="small"
                                            />
                                        )} */
                ]}
                dataSource={role.members}
            />
        </div>
    )
}

function RoleModal(): JSX.Element {
    const { editingRoleId } = useValues(roleBasedAccessControlLogic)
    const { setEditingRoleId, submitEditingRole, deleteRole } = useActions(roleBasedAccessControlLogic)
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
        <Form logic={roleBasedAccessControlLogic} formKey="editingRole" enableFormOnSubmit>
            <LemonModal
                isOpen={!!editingRoleId}
                title={!isEditing ? 'Create role' : `Edit role`}
                footer={
                    <>
                        <div className="flex-1">
                            {!isEditing ? (
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
