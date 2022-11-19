import { LemonDivider, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { Row } from 'antd'
import { useActions, useValues } from 'kea'
import { IconDelete } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonModal } from 'lib/components/LemonModal'
import { LemonSelectMultiple } from 'lib/components/LemonSelectMultiple/LemonSelectMultiple'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { useState } from 'react'
import { organizationLogic } from 'scenes/organizationLogic'
import { AccessLevel, Resource, RoleMemberType, UserType } from '~/types'
import { rolesLogic } from './rolesLogic'

export function CreateRoleModal(): JSX.Element {
    const {
        roleInFocus,
        createRoleModalShown,
        roleMembersToAdd,
        roleMembersInFocusLoading,
        addableMembers,
        rolesLoading,
        roleMembersInFocus,
        permissionsToSet,
    } = useValues(rolesLogic)
    const {
        setCreateRoleModalShown,
        setRoleMembersToAdd,
        createRole,
        deleteRoleMember,
        addRoleMembers,
        setPermission,
        setPermissionInPlace,
    } = useActions(rolesLogic)

    const { isAdminOrOwner } = useValues(organizationLogic)

    const [roleName, setRoleName] = useState('')

    const handleClose = (): void => {
        setCreateRoleModalShown(false)
        setRoleMembersToAdd([])
    }

    const handleSubmit = (): void => {
        createRole(roleName)
        setRoleName('')
    }

    const updatePermission = (newValue: null | AccessLevel): void => {
        if (newValue) {
            setPermission(Resource.FEATURE_FLAGS, newValue)
            setPermissionInPlace(Resource.FEATURE_FLAGS, newValue)
        }
    }

    const isNewRole = !roleInFocus

    return (
        <LemonModal
            onClose={handleClose}
            isOpen={createRoleModalShown}
            title={isNewRole ? 'Create Role' : `Edit ${roleInFocus.name} role`}
            footer={
                isNewRole && (
                    <LemonButton type="primary" disabled={rolesLoading} onClick={handleSubmit}>
                        {rolesLoading ? <Spinner monocolor /> : 'Create Role'}
                    </LemonButton>
                )
            }
        >
            {isNewRole && (
                <div className="mb-5">
                    <h5>Role Name</h5>
                    <LemonInput placeholder="Product" autoFocus value={roleName} onChange={setRoleName} />
                </div>
            )}
            {isAdminOrOwner && (
                <div className="mb-5">
                    <h5>Members</h5>
                    <div className="flex gap-2">
                        <div className="flex-1">
                            <LemonSelectMultiple
                                placeholder="Search for team members to add…"
                                value={roleMembersToAdd}
                                loading={roleMembersInFocusLoading}
                                onChange={(newValues) => setRoleMembersToAdd(newValues)}
                                filterOption={true}
                                mode="multiple"
                                data-attr="subscribed-emails"
                                options={usersLemonSelectOptions(addableMembers, 'uuid')}
                            />
                        </div>
                        {!isNewRole && (
                            <LemonButton
                                type="primary"
                                loading={roleMembersInFocusLoading}
                                disabled={roleMembersToAdd.length === 0}
                                onClick={() => addRoleMembers({ role: roleInFocus, membersToAdd: roleMembersToAdd })}
                            >
                                Add
                            </LemonButton>
                        )}
                    </div>
                </div>
            )}
            {!isNewRole && (
                <>
                    <h5>Role Members</h5>
                    {roleMembersInFocus.length > 0 ? (
                        <div
                            className="mt-2 pb-2 rounded overflow-y-auto"
                            style={{
                                maxHeight: 300,
                            }}
                        >
                            {roleMembersInFocus.map((member) => {
                                return (
                                    <MemberRow
                                        key={member.id}
                                        member={member}
                                        deleteMember={(roleMemberUuid) => deleteRoleMember({ roleMemberUuid })}
                                        isAdminOrOwner={!!isAdminOrOwner}
                                    />
                                )
                            })}
                        </div>
                    ) : (
                        <div className="text-muted mb-2">No members added yet</div>
                    )}
                </>
            )}
            <LemonDivider />
            <h5 className="mt-4">Permissions</h5>
            <Row justify="space-between" align="middle">
                <b className="">Feature Flags</b>
                <LemonSelect
                    disabled={!isAdminOrOwner}
                    value={permissionsToSet[Resource.FEATURE_FLAGS]}
                    onChange={updatePermission}
                    options={[
                        {
                            value: AccessLevel.WRITE,
                            label: 'View & Edit',
                        },
                        {
                            value: AccessLevel.READ,
                            label: 'View Only',
                        },
                        {
                            value: AccessLevel.CUSTOM_ASSIGNED,
                            label: 'View & Assigned Edit',
                        },
                    ]}
                />
            </Row>
        </LemonModal>
    )
}

function MemberRow({
    member,
    deleteMember,
    isAdminOrOwner,
}: {
    member: RoleMemberType
    deleteMember?: (roleMemberUuid: UserType['uuid']) => void
    isAdminOrOwner: boolean
}): JSX.Element {
    const { user } = member

    return (
        <div className="flex items-center justify-between mt-2 h-8">
            <ProfilePicture email={user.email} name={user.first_name} size="md" showName />
            {isAdminOrOwner && deleteMember && (
                <LemonButton
                    icon={<IconDelete />}
                    onClick={() => deleteMember(member.id)}
                    tooltip={'Remove user from role'}
                    status="primary-alt"
                    type="tertiary"
                    size="small"
                />
            )}
        </div>
    )
}
