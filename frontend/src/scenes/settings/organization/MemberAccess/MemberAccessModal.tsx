import { useActions, useValues } from 'kea'

import { IconExternal, IconInfo } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonModal,
    LemonSelect,
    LemonTable,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { capitalizeFirstLetter } from 'lib/utils'
import { fullName } from 'lib/utils'
import { pluralizeResource } from 'lib/utils/accessControlUtils'
import { membershipLevelToName, organizationMembershipLevelIntegers } from 'lib/utils/permissioning'
import { urls } from 'scenes/urls'

import { AccessControlLevel, OrganizationMemberType } from '~/types'

import { memberAccessModalLogic } from './memberAccessModalLogic'

export interface MemberAccessModalProps {
    member: OrganizationMemberType | null
}

export function MemberAccessModal({ member }: MemberAccessModalProps): JSX.Element | null {
    const logic = memberAccessModalLogic({ member })
    const {
        modalOpen,
        selectedMember,
        memberLevel,
        levelDescription,
        isOwnerOrAdmin,
        memberRoles,
        memberRoleIds,
        memberProjectAccess,
        memberResourceAccess,
        memberResourceOverrides,
        memberAccessDetailsLoading,
        hasUnsavedChanges,
        canEditMember,
        roles,
        resources,
    } = useValues(logic)
    const { closeModal, setMemberLevel, setMemberRoles, updateProjectAccess, updateResourceAccess, saveChanges } =
        useActions(logic)

    if (!selectedMember) {
        return null
    }

    return (
        <LemonModal
            isOpen={modalOpen}
            onClose={closeModal}
            title="Member access"
            width={640}
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveChanges}
                        disabledReason={!hasUnsavedChanges ? 'No changes to save' : undefined}
                    >
                        Save changes
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-6">
                {/* Basic info header */}
                <MemberBasicInfo member={selectedMember} />

                <LemonDivider />

                {/* Level section */}
                <MemberLevelSection
                    level={memberLevel}
                    description={levelDescription}
                    canEdit={canEditMember}
                    onLevelChange={setMemberLevel}
                />

                <LemonDivider />

                {/* Projects section */}
                <MemberProjectsSection
                    projectAccess={memberProjectAccess}
                    isOwnerOrAdmin={isOwnerOrAdmin}
                    canEdit={canEditMember}
                    onAccessChange={updateProjectAccess}
                    loading={memberAccessDetailsLoading}
                />

                <LemonDivider />

                {/* Roles section */}
                <MemberRolesSection
                    memberRoles={memberRoles}
                    memberRoleIds={memberRoleIds}
                    availableRoles={roles ?? []}
                    canEdit={canEditMember}
                    onRolesChange={setMemberRoles}
                />

                <LemonDivider />

                {/* Feature access section */}
                <MemberFeatureAccessSection
                    resourceAccess={memberResourceAccess}
                    resources={resources}
                    canEdit={canEditMember}
                    onAccessChange={updateResourceAccess}
                    loading={memberAccessDetailsLoading}
                />

                {/* Object-level overrides section */}
                {memberResourceOverrides.length > 0 && (
                    <>
                        <LemonDivider />
                        <MemberObjectOverridesSection overrides={memberResourceOverrides} />
                    </>
                )}
            </div>
        </LemonModal>
    )
}

function MemberBasicInfo({ member }: { member: OrganizationMemberType }): JSX.Element {
    return (
        <div className="flex gap-4 items-start">
            <ProfilePicture user={member.user} size="xl" />
            <div className="flex-1 space-y-1">
                <h3 className="mb-0 text-lg font-semibold">{fullName(member.user)}</h3>
                <p className="text-secondary mb-0">{member.user.email}</p>
                <div className="flex gap-4 text-sm text-secondary">
                    <span>
                        Joined: <TZLabel time={member.joined_at} />
                    </span>
                    <span>Last login: {member.last_login ? <TZLabel time={member.last_login} /> : 'Never'}</span>
                </div>
                <div className="mt-2">
                    <LemonTag type={member.is_2fa_enabled ? 'success' : 'warning'}>
                        {member.is_2fa_enabled ? '2FA enabled' : '2FA not enabled'}
                    </LemonTag>
                </div>
            </div>
        </div>
    )
}

function MemberLevelSection({
    level,
    description,
    canEdit,
    onLevelChange,
}: {
    level: OrganizationMembershipLevel
    description: string
    canEdit: boolean
    onLevelChange: (level: OrganizationMembershipLevel) => void
}): JSX.Element {
    const levelOptions = organizationMembershipLevelIntegers.map((l) => ({
        value: l,
        label: capitalizeFirstLetter(membershipLevelToName.get(l) ?? 'unknown'),
    }))

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <h4 className="mb-0 font-semibold">Level</h4>
            </div>
            <p className="text-secondary text-sm mb-2">{description}</p>
            <LemonSelect
                value={level}
                onChange={(newLevel) => onLevelChange(newLevel as OrganizationMembershipLevel)}
                options={levelOptions}
                disabled={!canEdit}
            />
        </div>
    )
}

function MemberProjectsSection({
    projectAccess,
    isOwnerOrAdmin,
    canEdit,
    onAccessChange,
    loading,
}: {
    projectAccess: { project: { id: number; name: string }; accessLevel: AccessControlLevel | null }[]
    isOwnerOrAdmin: boolean
    canEdit: boolean
    onAccessChange: (projectId: number, level: AccessControlLevel | null) => void
    loading: boolean
}): JSX.Element {
    const accessLevelOptions = [
        { value: null, label: 'No access' },
        { value: AccessControlLevel.Member, label: 'Member' },
        { value: AccessControlLevel.Admin, label: 'Admin' },
    ]

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <h4 className="mb-0 font-semibold">Projects</h4>
                <Link to={urls.settings('environment-access-control')}>
                    More project access settings
                    <IconExternal className="ml-1" />
                </Link>
            </div>

            {isOwnerOrAdmin ? (
                <LemonBanner type="info">
                    {`${projectAccess.length > 0 ? 'Owners and admins' : 'This member'} have${isOwnerOrAdmin ? '' : 's'} admin access to all projects.`}
                </LemonBanner>
            ) : (
                <LemonTable
                    loading={loading}
                    dataSource={projectAccess}
                    columns={[
                        {
                            title: 'Project',
                            dataIndex: 'project',
                            render: (_, { project }) => project.name,
                        },
                        {
                            title: 'Access',
                            key: 'access',
                            width: 150,
                            render: (_, { project, accessLevel }) => (
                                <LemonSelect
                                    value={accessLevel}
                                    onChange={(newLevel) => onAccessChange(project.id, newLevel)}
                                    options={accessLevelOptions}
                                    disabled={!canEdit}
                                    size="small"
                                />
                            ),
                        },
                    ]}
                    size="small"
                    emptyState="No projects in this organization"
                />
            )}
        </div>
    )
}

function MemberRolesSection({
    memberRoles,
    memberRoleIds,
    availableRoles,
    canEdit,
    onRolesChange,
}: {
    memberRoles: { id: string; name: string }[]
    memberRoleIds: string[]
    availableRoles: { id: string; name: string }[]
    canEdit: boolean
    onRolesChange: (roleIds: string[]) => void
}): JSX.Element {
    const roleOptions = availableRoles.map((role) => ({
        key: role.id,
        label: role.name,
    }))

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <div>
                    <h4 className="mb-0 font-semibold">Roles</h4>
                    <p className="text-secondary text-sm mb-0">
                        Roles grant permissions to groups of features. Members inherit permissions from all their
                        assigned roles.
                    </p>
                </div>
                <Link to={urls.settings('organization-roles')}>
                    Configure role permissions
                    <IconExternal className="ml-1" />
                </Link>
            </div>

            {availableRoles.length === 0 ? (
                <p className="text-muted mb-0">No roles defined in this organization.</p>
            ) : (
                <LemonInputSelect
                    value={memberRoleIds}
                    onChange={onRolesChange}
                    options={roleOptions}
                    mode="multiple"
                    placeholder="Select roles..."
                    disabled={!canEdit}
                />
            )}

            {memberRoles.length === 0 && availableRoles.length > 0 && (
                <p className="text-muted mb-0">No roles assigned</p>
            )}
        </div>
    )
}

function MemberFeatureAccessSection({
    resourceAccess,
    resources,
    canEdit,
    onAccessChange,
    loading,
}: {
    resourceAccess: Record<string, AccessControlLevel | null>
    resources: string[]
    canEdit: boolean
    onAccessChange: (resource: string, level: AccessControlLevel | null) => void
    loading: boolean
}): JSX.Element {
    const accessLevelOptions = [
        { value: null, label: 'No override' },
        { value: AccessControlLevel.None, label: 'No access' },
        { value: AccessControlLevel.Viewer, label: 'Viewer' },
        { value: AccessControlLevel.Editor, label: 'Editor' },
        { value: AccessControlLevel.Manager, label: 'Manager' },
    ]

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <div>
                    <h4 className="mb-0 font-semibold">Feature access</h4>
                    <p className="text-secondary text-sm mb-0">
                        Override access to specific features for this member. These take precedence over role
                        permissions.
                    </p>
                </div>
            </div>

            <LemonTable
                loading={loading}
                dataSource={resources.map((resource) => ({
                    resource,
                    accessLevel: resourceAccess[resource] ?? null,
                }))}
                columns={[
                    {
                        title: 'Feature',
                        dataIndex: 'resource',
                        render: (_, { resource }) => (
                            <span className="font-medium">
                                {capitalizeFirstLetter(pluralizeResource(resource as any))}
                            </span>
                        ),
                    },
                    {
                        title: 'Access',
                        key: 'access',
                        width: 150,
                        render: (_, { resource, accessLevel }) => (
                            <LemonSelect
                                value={accessLevel}
                                onChange={(newLevel) => onAccessChange(resource, newLevel)}
                                options={accessLevelOptions}
                                disabled={!canEdit}
                                size="small"
                                placeholder="No override"
                            />
                        ),
                    },
                    {
                        title: '',
                        key: 'info',
                        width: 40,
                        render: (_, { accessLevel }) => {
                            if (accessLevel === null) {
                                return null
                            }
                            return (
                                <Tooltip title="This is a member-level override">
                                    <IconInfo className="text-muted" />
                                </Tooltip>
                            )
                        },
                    },
                ]}
                size="small"
            />
        </div>
    )
}

function MemberObjectOverridesSection({
    overrides,
}: {
    overrides: { resource: string; resourceId: string; resourceName: string; accessLevel: AccessControlLevel }[]
}): JSX.Element {
    return (
        <div className="space-y-2">
            <div>
                <h4 className="mb-0 font-semibold">Specific overrides</h4>
                <p className="text-secondary text-sm mb-0">
                    Object-level access for specific dashboards, insights, etc.
                </p>
            </div>

            <LemonTable
                dataSource={overrides}
                columns={[
                    {
                        title: 'Object',
                        key: 'object',
                        render: (_, { resource, resourceName }) => (
                            <div>
                                <span className="font-medium">{resourceName}</span>
                                <span className="text-muted ml-2">({resource})</span>
                            </div>
                        ),
                    },
                    {
                        title: 'Access',
                        dataIndex: 'accessLevel',
                        width: 100,
                        render: (_, { accessLevel }) => <LemonTag>{capitalizeFirstLetter(accessLevel)}</LemonTag>,
                    },
                    {
                        title: '',
                        key: 'actions',
                        width: 40,
                        render: (_, { resource, resourceId }) => (
                            <Tooltip title="Edit access on the object's page">
                                <Link to={`/${resource}s/${resourceId}`}>
                                    <IconExternal />
                                </Link>
                            </Tooltip>
                        ),
                    },
                ]}
                size="small"
            />
        </div>
    )
}

// Standalone modal opener for use in the Members table
export function MemberAccessModalStandalone(): JSX.Element | null {
    const logic = memberAccessModalLogic({ member: null })
    const { modalOpen, selectedMember } = useValues(logic)

    if (!modalOpen || !selectedMember) {
        return null
    }

    return <MemberAccessModal member={selectedMember} />
}
