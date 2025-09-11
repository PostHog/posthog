import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonInput, LemonSwitch } from '@posthog/lemon-ui'

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
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter, fullName } from 'lib/utils'
import {
    getReasonForAccessLevelChangeProhibition,
    membershipLevelToName,
    organizationMembershipLevelIntegers,
} from 'lib/utils/permissioning'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { twoFactorLogic } from 'scenes/authentication/twoFactorLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, OrganizationMemberType } from '~/types'

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
    const { removeMember, changeMemberAccessLevel, loadMemberScopedApiKeys } = useActions(membersLogic)

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

    if (disallowedReason && !allowDeletion) {
        return null
    }

    return (
        <More
            overlay={
                <>
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

export function Members(): JSX.Element | null {
    const { filteredMembers, membersLoading, search } = useValues(membersLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const { setSearch, ensureAllMembersLoaded } = useActions(membersLogic)
    const { updateOrganization } = useActions(organizationLogic)
    const { openTwoFactorSetupModal } = useActions(twoFactorLogic)

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
            render: (_, member) =>
                member.user.uuid == user.uuid ? `${fullName(member.user)} (you)` : fullName(member.user),
            sorter: (a, b) => fullName(a.user).localeCompare(fullName(b.user)),
        },
        {
            title: 'Email',
            key: 'user_email',
            render: (_, member) => {
                return (
                    <>
                        {member.user.email}
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
        </>
    )
}
