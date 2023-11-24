import { LemonInput, LemonModal, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import {
    getReasonForAccessLevelChangeProhibition,
    membershipLevelToName,
    organizationMembershipLevelIntegers,
} from 'lib/utils/permissioning'
import { useState } from 'react'
import { Setup2FA } from 'scenes/authentication/Setup2FA'
import { membersLogic } from 'scenes/organization/membersLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { OrganizationMemberType } from '~/types'

function ActionsComponent(_: any, member: OrganizationMemberType): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { removeMember, changeMemberAccessLevel } = useActions(membersLogic)

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
                    {disallowedReason ? (
                        <div>{disallowedReason}</div>
                    ) : (
                        allowedLevels.map((listLevel) => (
                            <LemonButton
                                status="stealth"
                                fullWidth
                                key={`${member.user.uuid}-level-${listLevel}`}
                                onClick={(event) => {
                                    event.preventDefault()
                                    if (!user) {
                                        throw Error
                                    }
                                    if (listLevel === OrganizationMembershipLevel.Owner) {
                                        LemonDialog.open({
                                            title: `Transfer organization ownership to ${member.user.first_name}?`,
                                            description: `You will no longer be the owner of ${user.organization?.name}. After the transfer you will become an administrator.`,
                                            primaryButton: {
                                                status: 'danger',
                                                children: 'Transfer Ownership',
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
                                    <>Transfer organization ownership</>
                                ) : listLevel > member.level ? (
                                    <>Upgrade to {membershipLevelToName.get(listLevel)}</>
                                ) : (
                                    <>Downgrade to {membershipLevelToName.get(listLevel)}</>
                                )}
                            </LemonButton>
                        ))
                    )}
                    {allowDeletion ? (
                        <>
                            <LemonDivider />
                            <LemonButton
                                status="danger"
                                data-attr="delete-org-membership"
                                onClick={() => {
                                    if (!user) {
                                        throw Error
                                    }
                                    LemonDialog.open({
                                        title: `${
                                            member.user.uuid == user.uuid
                                                ? 'Leave'
                                                : `Remove ${member.user.first_name} from`
                                        } organization ${user.organization?.name}?`,
                                        primaryButton: {
                                            children: member.user.uuid == user.uuid ? 'Leave' : 'Remove',
                                            status: 'danger',
                                            onClick: () => removeMember(member),
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                        },
                                    })
                                }}
                                fullWidth
                            >
                                {member.user.uuid !== user.uuid ? 'Remove from organization' : 'Leave organization'}
                            </LemonButton>
                        </>
                    ) : null}
                </>
            }
        />
    )
}

export function Members(): JSX.Element | null {
    const { filteredMembers, membersLoading, search } = useValues(membersLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { setSearch } = useActions(membersLogic)
    const { updateOrganization } = useActions(organizationLogic)
    const [is2FAModalVisible, set2FAModalVisible] = useState(false)
    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)

    if (!user) {
        return null
    }

    const columns: LemonTableColumns<OrganizationMemberType> = [
        {
            key: 'user_profile_picture',
            render: function ProfilePictureRender(_, member) {
                return <ProfilePicture name={member.user.first_name} email={member.user.email} />
            },
            width: 32,
        },
        {
            title: 'Name',
            key: 'user_first_name',
            render: (_, member) =>
                member.user.uuid == user.uuid ? `${member.user.first_name} (me)` : member.user.first_name,
            sorter: (a, b) => a.user.first_name.localeCompare(b.user.first_name),
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
                                    <LemonTag type={'highlight'} data-attr="pending-email-verification">
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
                        {member.level === OrganizationMembershipLevel.Owner
                            ? 'Organization owner'
                            : `Project ${membershipLevelToName.get(member.level) ?? `unknown (${member.level})`}`}
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
                        {member.user.uuid == user.uuid && is2FAModalVisible && (
                            <LemonModal title="Set up or manage 2FA" onClose={() => set2FAModalVisible(false)}>
                                <Setup2FA
                                    onSuccess={() => {
                                        set2FAModalVisible(false)
                                        userLogic.actions.updateUser({})
                                        membersLogic.actions.loadMembers()
                                    }}
                                />
                            </LemonModal>
                        )}
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
                                        ? () => set2FAModalVisible(true)
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
            key: 'actions',
            width: 0,
            render: ActionsComponent,
        },
    ]

    return (
        <>
            <div className="flex items-center justify-between">
                <LemonInput type="search" placeholder="Search for members" value={search} onChange={setSearch} />
                <LemonSwitch
                    label="Enforce 2FA"
                    bordered
                    checked={currentOrganization?.enforce_2fa ? true : false}
                    onChange={(enforce_2fa) => updateOrganization({ enforce_2fa })}
                />
            </div>

            <LemonTable
                dataSource={filteredMembers}
                columns={columns}
                rowKey="id"
                style={{ marginTop: '1rem' }}
                loading={membersLoading}
                data-attr="org-members-table"
                defaultSorting={{ columnKey: 'level', order: -1 }}
                pagination={{ pageSize: 50 }}
            />
        </>
    )
}
