import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonInput, LemonSwitch, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { capitalizeFirstLetter, fullName } from 'lib/utils'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { twoFactorLogic } from 'scenes/authentication/twoFactorLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { roleAccessControlLogic } from '~/layout/navigation-3000/sidepanel/panels/access_control/roleAccessControlLogic'
import { AvailableFeature, OrganizationMemberType, RoleType } from '~/types'

import { MemberAccessModal } from './MemberAccess/MemberAccessModal'
import { memberAccessModalLogic } from './MemberAccess/memberAccessModalLogic'

function RemoveMemberModal({ member }: { member: OrganizationMemberType }): JSX.Element {
    const { user } = useValues(userLogic)
    const { scopedApiKeys } = useValues(membersLogic)

    return (
        <div className="max-w-xl">
            <p>
                {member.user.uuid === user?.uuid
                    ? 'Are you sure you want to leave this organization? This cannot be undone. If you leave, you will no longer have access to this organization.'
                    : 'Are you sure you want to remove this member? This cannot be undone. They will no longer have access to this organization.'}
            </p>
            {scopedApiKeys?.keys && scopedApiKeys.keys.length > 0 && (
                <div className="mt-4">
                    <LemonBanner type="warning" className="mb-2">
                        The following API keys which belong to {member.user.uuid == user?.uuid ? 'you' : 'this member'}{' '}
                        will lose access to this organization and will stop working immediately. Please confirm they
                        will not affect any services that depend on them before removing{' '}
                        {member.user.uuid == user?.uuid ? 'yourself' : 'this member'}.
                    </LemonBanner>
                    <LemonTable
                        dataSource={scopedApiKeys.keys}
                        columns={[
                            {
                                title: 'Name',
                                dataIndex: 'name',
                                key: 'name',
                            },
                            {
                                title: 'Last used',
                                dataIndex: 'last_used_at',
                                key: 'last_used_at',
                                render: (last_used_at) => (last_used_at ? <TZLabel time={last_used_at} /> : 'Never'),
                            },
                        ]}
                    />
                </div>
            )}
        </div>
    )
}

function ActionsComponent(_: any, member: OrganizationMemberType): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { removeMember, loadMemberScopedApiKeys } = useActions(membersLogic)
    const { openModal } = useActions(memberAccessModalLogic({ member: null }))

    if (!user) {
        return null
    }

    const currentMembershipLevel = currentOrganization?.membership_level ?? -1

    const allowDeletion =
        // higher-ranked users cannot be removed, at the same time the currently logged-in user can leave any time
        ((currentMembershipLevel >= OrganizationMembershipLevel.Admin && member.level <= currentMembershipLevel) ||
            member.user.uuid === user.uuid) &&
        // unless that user is the organization's owner, in which case they can't leave
        member.level !== OrganizationMembershipLevel.Owner

    const canEditAccess =
        currentMembershipLevel >= OrganizationMembershipLevel.Admin &&
        member.user.uuid !== user.uuid &&
        member.level !== OrganizationMembershipLevel.Owner

    if (!canEditAccess && !allowDeletion) {
        return null
    }

    return (
        <More
            overlay={
                <>
                    {canEditAccess && (
                        <LemonButton fullWidth onClick={() => openModal(member)} data-attr="edit-member-access">
                            Edit access
                        </LemonButton>
                    )}
                    {allowDeletion && (
                        <LemonButton
                            status="danger"
                            data-attr="delete-org-membership"
                            onClick={() => {
                                if (!user) {
                                    throw Error
                                }
                                loadMemberScopedApiKeys(member)
                                LemonDialog.open({
                                    title: `${
                                        member.user.uuid == user.uuid ? 'Leave' : `Remove ${fullName(member.user)} from`
                                    } organization ${user.organization?.name}?`,
                                    primaryButton: {
                                        children: member.user.uuid == user.uuid ? 'Leave' : 'Remove',
                                        status: 'danger',
                                        onClick: () => removeMember(member),
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                    },
                                    content: <RemoveMemberModal member={member} />,
                                })
                            }}
                            fullWidth
                        >
                            {member.user.uuid !== user.uuid ? 'Remove from organization' : 'Leave organization'}
                        </LemonButton>
                    )}
                </>
            }
        />
    )
}

function MemberLevelTooltip({ level }: { level: OrganizationMembershipLevel }): JSX.Element {
    const descriptions: Record<OrganizationMembershipLevel, string> = {
        [OrganizationMembershipLevel.Member]:
            'Members have access based on their project-specific permissions and roles.',
        [OrganizationMembershipLevel.Admin]:
            'Admins can manage organization settings and members. They have admin access to all projects.',
        [OrganizationMembershipLevel.Owner]:
            'Owners have full control over the organization, including billing and member management.',
    }

    return (
        <Tooltip title={descriptions[level] || 'Unknown level'}>
            <span className="inline-flex items-center gap-1">
                <LemonTag data-attr="membership-level">
                    {capitalizeFirstLetter(membershipLevelToName.get(level) ?? `unknown (${level})`)}
                </LemonTag>
                <IconInfo className="text-muted text-sm" />
            </span>
        </Tooltip>
    )
}

function ProjectsPreview({ member }: { member: OrganizationMemberType }): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const projects = currentOrganization?.projects ?? []

    // Owners and admins have access to all projects
    if (member.level >= OrganizationMembershipLevel.Admin) {
        return <span className="text-secondary">All projects</span>
    }

    // For regular members, we'd need to fetch their project access
    // For now, show a placeholder that will be populated when the access data is loaded
    if (projects.length === 0) {
        return <span className="text-muted">No projects</span>
    }

    // Show first two project names as a preview
    const firstTwo = projects.slice(0, 2).map((p) => p.name)
    const remaining = projects.length - 2

    if (remaining > 0) {
        return (
            <Tooltip title={projects.map((p) => p.name).join(', ')}>
                <span>
                    {firstTwo.join(', ')} <span className="text-muted">+{remaining}</span>
                </span>
            </Tooltip>
        )
    }

    return <span>{firstTwo.join(', ')}</span>
}

function RolesPreview({ member }: { member: OrganizationMemberType }): JSX.Element {
    const { roles } = useValues(roleAccessControlLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    if (!hasAvailableFeature(AvailableFeature.ROLE_BASED_ACCESS)) {
        return <span className="text-muted">No roles</span>
    }

    if (!roles || roles.length === 0) {
        return <span className="text-muted">No roles</span>
    }

    // Find roles that include this member
    const memberRoles = roles.filter((role: RoleType) =>
        role.members.some((roleMember) => roleMember.user.uuid === member.user.uuid)
    )

    if (memberRoles.length === 0) {
        return <span className="text-muted">No roles</span>
    }

    return (
        <div className="flex gap-1 flex-wrap">
            {memberRoles.slice(0, 2).map((role: RoleType) => (
                <LemonTag key={role.id} type="default">
                    {role.name}
                </LemonTag>
            ))}
            {memberRoles.length > 2 && (
                <Tooltip title={memberRoles.map((r: RoleType) => r.name).join(', ')}>
                    <LemonTag type="muted">+{memberRoles.length - 2}</LemonTag>
                </Tooltip>
            )}
        </div>
    )
}

function FeaturesPreview({ member }: { member: OrganizationMemberType }): JSX.Element {
    // Owners and admins have access to all features
    if (member.level >= OrganizationMembershipLevel.Admin) {
        return <span className="text-secondary">All features</span>
    }

    // For regular members, show default access (full feature access data would require loading)
    return <span className="text-secondary">Default access</span>
}

export function Members(): JSX.Element | null {
    const { filteredMembers, membersLoading, search } = useValues(membersLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const { setSearch, ensureAllMembersLoaded } = useActions(membersLogic)
    const { updateOrganization } = useActions(organizationLogic)
    const { openTwoFactorSetupModal } = useActions(twoFactorLogic)
    const { openModal } = useActions(memberAccessModalLogic({ member: null }))
    const { modalOpen, selectedMember } = useValues(memberAccessModalLogic({ member: null }))

    const twoFactorRestrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })
    const membersCanInviteRestrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })
    const membersCanUsePersonalApiKeysRestrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    useOnMountEffect(ensureAllMembersLoaded)

    if (!user) {
        return null
    }

    const canEditMembers = (currentOrganization?.membership_level ?? 0) >= OrganizationMembershipLevel.Admin

    const columns: LemonTableColumns<OrganizationMemberType> = [
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
            render: (_, member) => (
                <span className="ph-no-capture">
                    {member.user.uuid == user.uuid ? `${fullName(member.user)} (you)` : fullName(member.user)}
                </span>
            ),
            sorter: (a, b) => fullName(a.user).localeCompare(fullName(b.user)),
        },
        {
            title: 'Email',
            key: 'user_email',
            render: (_, member) => {
                return (
                    <>
                        <span className="ph-no-capture">{member.user.email}</span>
                        {!member.user.is_email_verified &&
                            !member.has_social_auth &&
                            preflight?.email_service_available && (
                                <>
                                    {' '}
                                    <LemonTag type="highlight" data-attr="pending-email-verification">
                                        pending email verification
                                    </LemonTag>
                                </>
                            )}
                    </>
                )
            },
            sorter: (a, b) => a.user.email.localeCompare(b.user.email),
        },
        {
            title: '2FA',
            dataIndex: 'is_2fa_enabled',
            key: 'is_2fa_enabled',
            render: function LevelRender(_, member) {
                return (
                    <>
                        <Tooltip
                            title={
                                member.user.uuid == user.uuid && !member.is_2fa_enabled
                                    ? 'Click to setup 2FA for your account'
                                    : ''
                            }
                        >
                            <LemonTag
                                onClick={
                                    member.user.uuid == user.uuid && !member.is_2fa_enabled
                                        ? () => openTwoFactorSetupModal()
                                        : undefined
                                }
                                data-attr="2fa-enabled"
                                type={member.is_2fa_enabled ? 'success' : 'warning'}
                            >
                                {member.is_2fa_enabled ? 'Enabled' : 'Not enabled'}
                            </LemonTag>
                        </Tooltip>
                    </>
                )
            },
            sorter: (a, b) => (a.is_2fa_enabled != b.is_2fa_enabled ? 1 : 0),
        },
        {
            title: 'Projects',
            key: 'projects',
            render: (_, member) => <ProjectsPreview member={member} />,
        },
        {
            title: 'Level',
            dataIndex: 'level',
            key: 'level',
            render: function LevelRender(_, member) {
                return <MemberLevelTooltip level={member.level} />
            },
            sorter: (a, b) => a.level - b.level,
        },
        {
            title: 'Roles',
            key: 'roles',
            render: (_, member) => <RolesPreview member={member} />,
        },
        {
            title: 'Features',
            key: 'features',
            render: (_, member) => <FeaturesPreview member={member} />,
        },
        {
            key: 'actions',
            width: 0,
            render: ActionsComponent,
        },
    ]

    const handleRowClick = (member: OrganizationMemberType): void => {
        if (canEditMembers && member.user.uuid !== user.uuid && member.level !== OrganizationMembershipLevel.Owner) {
            openModal(member)
        }
    }

    return (
        <>
            <LemonInput type="search" placeholder="Search for members" value={search} onChange={setSearch} />

            <LemonTable
                dataSource={filteredMembers ?? []}
                columns={columns}
                rowKey="id"
                style={{ marginTop: '1rem' }}
                loading={membersLoading}
                data-attr="org-members-table"
                defaultSorting={{ columnKey: 'level', order: -1 }}
                pagination={{ pageSize: 50 }}
                onRow={(member) => ({
                    onClick: () => handleRowClick(member),
                    className:
                        canEditMembers &&
                        member.user.uuid !== user.uuid &&
                        member.level !== OrganizationMembershipLevel.Owner
                            ? 'cursor-pointer hover:bg-surface-highlight'
                            : '',
                })}
            />

            <h3 className="mt-4">Two-factor authentication</h3>
            <PayGateMini feature={AvailableFeature.TWOFA_ENFORCEMENT}>
                <p>Require all organization members to use two-factor authentication.</p>
                <LemonSwitch
                    label="Enforce 2FA"
                    bordered
                    checked={!!currentOrganization?.enforce_2fa}
                    onChange={(enforce_2fa) => updateOrganization({ enforce_2fa })}
                    disabledReason={twoFactorRestrictionReason}
                />
            </PayGateMini>

            <h3 className="mt-4">Invite settings</h3>
            <PayGateMini feature={AvailableFeature.ORGANIZATION_INVITE_SETTINGS}>
                <p>Control who can send organization invites.</p>
                <LemonSwitch
                    label={
                        <span>
                            Members can invite others to join <i>{currentOrganization?.name}</i>
                        </span>
                    }
                    bordered
                    data-attr="org-members-can-invite-toggle"
                    checked={!!currentOrganization?.members_can_invite}
                    onChange={(members_can_invite) => updateOrganization({ members_can_invite })}
                    disabledReason={membersCanInviteRestrictionReason}
                />
            </PayGateMini>

            {posthog.isFeatureEnabled(FEATURE_FLAGS.MEMBERS_CAN_USE_PERSONAL_API_KEYS) && (
                <>
                    <h3 className="mt-4">Security settings</h3>
                    <PayGateMini feature={AvailableFeature.ORGANIZATION_SECURITY_SETTINGS}>
                        <p>Configure security permissions for organization members.</p>
                        <LemonSwitch
                            label={
                                <span>
                                    Members can use personal API keys{' '}
                                    <Tooltip title="Organization admins and owners can always use personal API keys regardless of this setting.">
                                        <IconInfo className="mr-1" />
                                    </Tooltip>
                                </span>
                            }
                            bordered
                            data-attr="org-members-can-use-personal-api-keys-toggle"
                            checked={!!currentOrganization?.members_can_use_personal_api_keys}
                            onChange={(members_can_use_personal_api_keys) =>
                                updateOrganization({ members_can_use_personal_api_keys })
                            }
                            disabledReason={membersCanUsePersonalApiKeysRestrictionReason}
                        />
                    </PayGateMini>
                </>
            )}

            {/* Member Access Modal */}
            {modalOpen && selectedMember && <MemberAccessModal member={selectedMember} />}
        </>
    )
}
