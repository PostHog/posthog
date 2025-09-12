import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useMemo, useState } from 'react'

import { IconInfo, IconPlus } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    ProfileBubbles,
    ProfilePicture,
} from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { fullName } from 'lib/utils'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, RoleType } from '~/types'

import { roleAccessControlLogic } from './roleAccessControlLogic'

export function RolesAccessControls(): JSX.Element {
    const { sortedRoles, rolesLoading, selectedRoleId } = useValues(roleAccessControlLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    const { selectRoleId, setEditingRoleId } = useActions(roleAccessControlLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const defaultRoleRestrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const columns: LemonTableColumns<RoleType> = [
        {
            title: 'Role',
            key: 'role',
            width: 300,
            render: (_, role) => {
                const isDefaultRole = role?.id === currentOrganization?.default_role_id
                return (
                    <div className="flex items-center gap-2">
                        <LemonTableLink
                            onClick={
                                role
                                    ? () => (role.id === selectedRoleId ? selectRoleId(null) : selectRoleId(role.id))
                                    : undefined
                            }
                            title={role?.name ?? 'Default'}
                        />
                        {isDefaultRole && (
                            <LemonTag type="primary" size="small">
                                Default
                            </LemonTag>
                        )}
                    </div>
                )
            },
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

            <div>
                <LemonTable
                    columns={columns}
                    dataSource={sortedRoles ?? []}
                    loading={rolesLoading}
                    expandable={{
                        isRowExpanded: (role) => !!selectedRoleId && role?.id === selectedRoleId,
                        onRowExpand: (role) => (role ? selectRoleId(role.id) : undefined),
                        onRowCollapse: () => selectRoleId(null),
                        expandedRowRender: (role) => (role ? <RoleDetails roleId={role?.id} /> : null),
                        rowExpandable: (role) => !!role,
                    }}
                />

                <LemonButton
                    className="mt-2"
                    type="primary"
                    onClick={() => setEditingRoleId('new')}
                    icon={<IconPlus />}
                    disabledReason={defaultRoleRestrictionReason}
                >
                    Add a role
                </LemonButton>

                <RoleModal />

                <div className="my-6">
                    <LemonDivider />
                </div>

                <h4 className="mb-2">Default role for new members</h4>
                <p className="text-muted mb-2">
                    Automatically assign a role to new members when they join the organization.
                    <Tooltip title="When a new user joins your organization (via invite or signup), they will automatically be added to this role, inheriting all its permissions. This helps ensure consistent access control for new team members.">
                        <IconInfo className="ml-1" />
                    </Tooltip>
                </p>
                <div className="max-w-80">
                    <LemonSelect
                        fullWidth
                        value={currentOrganization?.default_role_id || null}
                        onChange={(value) => {
                            guardAvailableFeature(
                                AvailableFeature.ADVANCED_PERMISSIONS,
                                updateOrganization.bind(null, { default_role_id: value })
                            )
                        }}
                        options={[
                            { value: null, label: 'No default role' },
                            ...(sortedRoles?.map((role) => ({
                                value: role.id,
                                label: role.name,
                                element: (
                                    <div>
                                        {role.name}
                                        {role.id === currentOrganization?.default_role_id && (
                                            <LemonTag type="primary" className="ml-2" size="small">
                                                Current default
                                            </LemonTag>
                                        )}
                                    </div>
                                ),
                            })) || []),
                        ]}
                        placeholder="Select a default role..."
                        loading={rolesLoading}
                        disabledReason={defaultRoleRestrictionReason}
                    />
                </div>
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
    const { currentOrganization } = useValues(organizationLogic)
    const isEditing = editingRoleId !== 'new'

    const isDefaultRole = currentOrganization?.default_role_id === editingRoleId

    const onDelete = (): void => {
        const baseContent = 'Are you sure you want to delete this role? This action cannot be undone.'

        LemonDialog.open({
            title: 'Delete role',
            maxWidth: 400,
            content: (
                <div>
                    <p>{baseContent}</p>
                    {isDefaultRole && (
                        <p className="text-warning font-medium mt-2">
                            ⚠️ This role is currently set as the default for new members and will be cleared from
                            organization settings.
                        </p>
                    )}
                </div>
            ),
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
