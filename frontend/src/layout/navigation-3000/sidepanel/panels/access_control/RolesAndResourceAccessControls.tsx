import {
    LemonButton,
    LemonSelect,
    LemonSelectMultiple,
    LemonTable,
    LemonTableColumns,
    ProfileBubbles,
    ProfilePicture,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'kea-forms'
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
        selectedRole,
    } = useValues(roleBasedAccessControlLogic)

    const { updateRoleBasedAccessControls, selectRole } = useActions(roleBasedAccessControlLogic)

    const columns: LemonTableColumns<RoleWithResourceAccessControls> = [
        {
            title: 'Role',
            key: 'role',
            width: 0,
            render: (_, { role }) => (
                <span className="whitespace-nowrap">
                    <LemonTableLink onClick={() => selectRole(role)} title={role.name} />
                </span>
            ),
        },
        {
            title: 'Members',
            key: 'members',
            render: (_, { role }) => {
                return (
                    <ProfileBubbles
                        people={role.members.map((member) => ({
                            email: member.user.email,
                            name: member.user.first_name,
                            title: `${member.user.first_name} <${member.user.email}>`,
                        }))}
                        onClick={() => selectRole(role)}
                    />
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
                    isRowExpanded: (record) => !!selectedRole && record.role.id === selectedRole.id,
                    onRowExpand: (record) => selectRole(record.role),
                    onRowCollapse: () => selectRole(null),
                    expandedRowRender: ({ role }) => <RoleDetails role={role} />,
                }}
            />

            <LemonButton type="primary" onClick={() => alert('todo')}>
                Create role
            </LemonButton>
        </div>
    )
}

function RoleDetails({ role }: { role: RoleType }): JSX.Element {
    const { user } = useValues(userLogic)
    const { sortedMembers } = useValues(roleBasedAccessControlLogic)
    const { addMembersToRole, removeMemberFromRole } = useActions(roleBasedAccessControlLogic)
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
                    <LemonButton type="secondary" onClick={() => alert('todo')}>
                        Rename
                    </LemonButton>
                    <LemonButton type="secondary" status="danger" onClick={() => alert('todo')}>
                        Delete role
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
