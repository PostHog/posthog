import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonInput, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { projectDataFreshnessLogic } from 'lib/components/Account/projectDataFreshnessLogic'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import {
    getReasonForAccessLevelChangeProhibition,
    membershipLevelToName,
    organizationMembershipLevelIntegers,
} from 'lib/utils/permissioning'
import { capitalizeFirstLetter, fullName } from 'lib/utils/strings'
import { twoFactorLogic } from 'scenes/authentication/two-factor-setup/twoFactorLogic'
import { membersExportLogic } from 'scenes/organization/membersExportLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, OrganizationMemberType } from '~/types'

import { memberDisplayName } from './memberDisplayName'
import { accessibleProjects, orderByActivity } from './memberProjectAccess'
import { memberProjectAccessLogic } from './memberProjectAccessLogic'
import { MemberProjectAccessModal } from './MemberProjectAccessModal'

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
                        The following personal API keys which belong to{' '}
                        {member.user.uuid == user?.uuid ? 'you' : 'this member'} will lose access to this organization
                        and will stop working immediately. Please confirm they will not affect any services that depend
                        on them before removing {member.user.uuid == user?.uuid ? 'yourself' : 'this member'}.
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
    const { removeMember, changeMemberAccessLevel, loadMemberScopedApiKeys } = useActions(membersLogic)
    const { openProjectAccessModal } = useActions(memberProjectAccessLogic)

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

    const myMembershipLevel = currentOrganization ? currentOrganization.membership_level : null

    const allowedLevels = organizationMembershipLevelIntegers.filter(
        (listLevel) => !getReasonForAccessLevelChangeProhibition(myMembershipLevel, user, member, listLevel)
    )
    const disallowedReason = getReasonForAccessLevelChangeProhibition(myMembershipLevel, user, member, allowedLevels)

    return (
        <More
            overlay={
                <>
                    <LemonButton
                        fullWidth
                        onClick={() => openProjectAccessModal(member)}
                        data-attr="org-member-manage-project-access"
                    >
                        Manage project access
                    </LemonButton>
                    {!disallowedReason &&
                        allowedLevels.map((listLevel) => (
                            <LemonButton
                                fullWidth
                                key={`${member.user.uuid}-level-${listLevel}`}
                                onClick={(event) => {
                                    event.preventDefault()
                                    if (!user) {
                                        throw Error
                                    }
                                    if (listLevel === OrganizationMembershipLevel.Owner) {
                                        LemonDialog.open({
                                            title: `Add additional owner to ${user.organization?.name}?`,
                                            description: `Please confirm that you would like to make ${fullName(
                                                member.user
                                            )} an owner of ${user.organization?.name}.`,
                                            primaryButton: {
                                                status: 'danger',
                                                children: `Make ${fullName(member.user)} an owner`,
                                                onClick: () => changeMemberAccessLevel(member, listLevel),
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                            },
                                        })
                                    } else {
                                        changeMemberAccessLevel(member, listLevel)
                                    }
                                }}
                                data-test-level={listLevel}
                            >
                                {listLevel === OrganizationMembershipLevel.Owner ? (
                                    <>Make owner</>
                                ) : listLevel > member.level ? (
                                    <>Upgrade to {membershipLevelToName.get(listLevel)}</>
                                ) : (
                                    <>Downgrade to {membershipLevelToName.get(listLevel)}</>
                                )}
                            </LemonButton>
                        ))}
                    {allowDeletion && (
                        <>
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
                                            member.user.uuid == user.uuid
                                                ? 'Leave'
                                                : `Remove ${fullName(member.user)} from`
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
                        </>
                    )}
                </>
            }
        />
    )
}

const PROJECT_TAGS_SHOWN = 3

function ProjectAccessCell({ member }: { member: OrganizationMemberType }): JSX.Element {
    const { projectAccess, projectAccessLoading } = useValues(memberProjectAccessLogic)
    const { openProjectAccessModal } = useActions(memberProjectAccessLogic)
    const { freshnessByTeamId } = useValues(projectDataFreshnessLogic)

    if (projectAccessLoading) {
        return <LemonSkeleton className="h-5 w-32" />
    }
    // A failed load must not read as "this member has no projects"
    if (!projectAccess) {
        return <span className="text-muted">–</span>
    }

    const projects = orderByActivity(accessibleProjects(projectAccess[member.id] ?? []), freshnessByTeamId)
    if (projects.length === 0) {
        return <span className="text-muted">No projects</span>
    }

    const visibleProjects = projects.slice(0, PROJECT_TAGS_SHOWN)
    const hiddenCount = projects.length - visibleProjects.length

    return (
        <div className="flex flex-wrap gap-1 items-center">
            {visibleProjects.map((project) => (
                <LemonTag
                    key={project.team_id}
                    type="default"
                    className="max-w-40 truncate"
                    onClick={() => openProjectAccessModal(member)}
                >
                    {project.team_name}
                </LemonTag>
            ))}
            {hiddenCount > 0 && (
                <Link
                    className="text-warning text-xs ml-1"
                    onClick={() => openProjectAccessModal(member)}
                    data-attr="org-member-project-access-more"
                >
                    {`+${hiddenCount} more`}
                </Link>
            )}
        </div>
    )
}

export function Members(): JSX.Element | null {
    const { filteredMembers, members, membersLoading, search } = useValues(membersLogic)
    const { projectAccess } = useValues(memberProjectAccessLogic)
    const { downloadMembersListDisabledReason } = useValues(membersExportLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const { setSearch, ensureAllMembersLoaded } = useActions(membersLogic)
    const { downloadMembersList } = useActions(membersExportLogic)
    const { updateOrganization } = useActions(organizationLogic)
    const { openTwoFactorSetupModal } = useActions(twoFactorLogic)

    const adminRestrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })
    const hasHiddenMembers =
        (members?.length ?? 0) > 0 && (members?.length ?? 0) < (currentOrganization?.member_count ?? 0)

    useOnMountEffect(ensureAllMembersLoaded)

    if (!user) {
        return null
    }

    const columns: LemonTableColumns<OrganizationMemberType> = [
        {
            key: 'user_profile_picture',
            render: function ProfilePictureRender(_, member) {
                return <ProfilePicture user={member.user} />
            },
            width: 32,
        },
        {
            title: 'Member',
            key: 'user_name',
            render: (_, member) => (
                <div className="flex flex-col py-1">
                    <span className="ph-no-capture font-medium">
                        {member.user.uuid == user.uuid
                            ? `${memberDisplayName(member)} (you)`
                            : memberDisplayName(member)}
                    </span>
                    {fullName(member.user) && (
                        <span className="ph-no-capture text-secondary text-xs">{member.user.email}</span>
                    )}
                    {!member.user.is_email_verified &&
                        !member.has_social_auth &&
                        preflight?.email_service_available && (
                            <LemonTag
                                type="highlight"
                                className="self-start mt-1"
                                data-attr="pending-email-verification"
                            >
                                pending email verification
                            </LemonTag>
                        )}
                </div>
            ),
            sorter: (a, b) => memberDisplayName(a).localeCompare(memberDisplayName(b)),
        },
        {
            title: 'Level',
            dataIndex: 'level',
            key: 'level',
            render: function LevelRender(_, member) {
                return (
                    <LemonTag data-attr="membership-level">
                        {capitalizeFirstLetter(membershipLevelToName.get(member.level) ?? `unknown (${member.level})`)}
                    </LemonTag>
                )
            },
            sorter: (a, b) => a.level - b.level,
        },
        {
            title: 'Project access',
            key: 'project_access',
            render: (_, member) => <ProjectAccessCell member={member} />,
            sorter: (a, b) =>
                accessibleProjects(projectAccess?.[a.id] ?? []).length -
                accessibleProjects(projectAccess?.[b.id] ?? []).length,
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
                                {member.is_2fa_enabled ? '2FA enabled' : '2FA not enabled'}
                            </LemonTag>
                        </Tooltip>
                    </>
                )
            },
            sorter: (a, b) => (a.is_2fa_enabled != b.is_2fa_enabled ? 1 : 0),
        },
        {
            title: 'Joined',
            dataIndex: 'joined_at',
            key: 'joined_at',
            render: function RenderJoinedAt(joinedAt) {
                return (
                    <div className="whitespace-nowrap">
                        <TZLabel time={joinedAt as string} />
                    </div>
                )
            },
            sorter: (a, b) => a.joined_at.localeCompare(b.joined_at),
        },
        {
            title: 'Last Logged In',
            dataIndex: 'last_login',
            key: 'last_login',
            render: function RenderLastLogin(lastLogin) {
                return (
                    <div className="whitespace-nowrap">
                        {lastLogin ? <TZLabel time={lastLogin as string} /> : 'Never'}
                    </div>
                )
            },
            sorter: (a, b) => new Date(a.last_login ?? 0).getTime() - new Date(b.last_login ?? 0).getTime(),
        },
        {
            key: 'actions',
            width: 0,
            render: ActionsComponent,
        },
    ]

    return (
        <>
            <div className="flex flex-wrap gap-2 justify-between items-center">
                <LemonInput
                    type="search"
                    placeholder="Search for members"
                    value={search}
                    onChange={setSearch}
                    className="flex-1 basis-[min(100%,18rem)]"
                />
                {!adminRestrictionReason && (
                    <LemonButton
                        type="secondary"
                        onClick={downloadMembersList}
                        disabledReason={downloadMembersListDisabledReason}
                        data-attr="org-members-download-csv"
                    >
                        Download members list
                    </LemonButton>
                )}
            </div>

            <MemberProjectAccessModal />
            <LemonTable
                dataSource={filteredMembers ?? []}
                columns={columns}
                rowKey="id"
                style={{ marginTop: '1rem' }}
                loading={membersLoading}
                data-attr="org-members-table"
                defaultSorting={{ columnKey: 'level', order: -1 }}
                pagination={{ pageSize: 50 }}
                footer={
                    hasHiddenMembers && (
                        <div className="flex items-center gap-2 px-3 py-2">
                            <div className="flex">
                                {[0, 1, 2].map((index) => (
                                    <ProfilePicture
                                        key={index}
                                        name="?"
                                        index={index}
                                        size="md"
                                        className={index > 0 ? '-ml-1.5' : ''}
                                    />
                                ))}
                            </div>
                            <span className="text-secondary">
                                Other organization members{' '}
                                <Tooltip title="Your organization only shows the full member list to admins.">
                                    <IconInfo className="text-base align-middle" />
                                </Tooltip>
                            </span>
                        </div>
                    )
                }
            />
            <h3 className="mt-4">Two-factor authentication</h3>
            <PayGateMini
                feature={AvailableFeature.TWOFA_ENFORCEMENT}
                featureDetail="organization-members-two-factor-authentication"
            >
                <p>Require all organization members to use two-factor authentication.</p>
                <LemonSwitch
                    label="Enforce 2FA"
                    bordered
                    checked={!!currentOrganization?.enforce_2fa}
                    onChange={(enforce_2fa) => updateOrganization({ enforce_2fa })}
                    disabledReason={adminRestrictionReason}
                />
            </PayGateMini>

            <h3 className="mt-4">Invite settings</h3>
            <PayGateMini
                feature={AvailableFeature.ORGANIZATION_INVITE_SETTINGS}
                featureDetail="organization-member-and-project-invites"
            >
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
                    disabledReason={adminRestrictionReason}
                />
                <p className="mt-4">
                    Control who can create new projects. Admins and owners can always create projects.
                </p>
                <LemonSwitch
                    label={
                        <span>
                            Members can create new projects in <i>{currentOrganization?.name}</i>
                        </span>
                    }
                    bordered
                    data-attr="org-members-can-create-projects-toggle"
                    checked={!!currentOrganization?.members_can_create_projects}
                    onChange={(members_can_create_projects) => updateOrganization({ members_can_create_projects })}
                    disabledReason={adminRestrictionReason}
                />
            </PayGateMini>

            {posthog.isFeatureEnabled(FEATURE_FLAGS.MEMBERS_CAN_USE_PERSONAL_API_KEYS) && (
                <>
                    <h3 className="mt-4">Security settings</h3>
                    <PayGateMini
                        feature={AvailableFeature.ORGANIZATION_SECURITY_SETTINGS}
                        featureDetail="organization-members-personal-api-key-access"
                    >
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
                            disabledReason={adminRestrictionReason}
                        />
                    </PayGateMini>
                </>
            )}
        </>
    )
}
