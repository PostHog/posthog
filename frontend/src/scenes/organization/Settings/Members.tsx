import React from 'react'
import { Modal, Input } from 'antd'
import { useValues, useActions } from 'kea'
import { membersLogic } from './membersLogic'
import { ExclamationCircleOutlined, SwapOutlined } from '@ant-design/icons'
import { OrganizationMembershipLevel } from 'lib/constants'
import { OrganizationMemberType, UserType } from '~/types'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import {
    getReasonForAccessLevelChangeProhibition,
    organizationMembershipLevelIntegers,
    membershipLevelToName,
} from 'lib/utils/permissioning'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { TZLabel } from 'lib/components/TimezoneAware'
import { LemonButton } from 'lib/components/LemonButton'
import { More } from 'lib/components/LemonButton/More'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { LemonDivider } from 'lib/components/LemonDivider'

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
                                type="stealth"
                                fullWidth
                                key={`${member.user.uuid}-level-${listLevel}`}
                                onClick={(event) => {
                                    event.preventDefault()
                                    if (!user) {
                                        throw Error
                                    }
                                    if (listLevel === OrganizationMembershipLevel.Owner) {
                                        Modal.confirm({
                                            centered: true,
                                            title: `Transfer organization ownership to ${member.user.first_name}?`,
                                            content: `You will no longer be the owner of ${user.organization?.name}. After the transfer you will become an administrator.`,
                                            icon: <SwapOutlined />,
                                            okType: 'danger',
                                            okText: 'Transfer Ownership',
                                            onOk() {
                                                changeMemberAccessLevel(member, listLevel)
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
                                type="stealth"
                                status="danger"
                                onClick={() => {
                                    if (!user) {
                                        throw Error
                                    }
                                    Modal.confirm({
                                        title: `${
                                            member.user.uuid == user.uuid
                                                ? 'Leave'
                                                : `Remove ${member.user.first_name} from`
                                        } organization ${user.organization?.name}?`,
                                        icon: <ExclamationCircleOutlined />,
                                        okText: member.user.uuid == user.uuid ? 'Leave' : 'Remove',
                                        okType: 'danger',
                                        cancelText: 'Cancel',
                                        onOk() {
                                            removeMember(member)
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

export interface MembersProps {
    /** Currently logged-in user. */
    user: UserType
}

export function Members({ user }: MembersProps): JSX.Element {
    const { filteredMembers, membersLoading, search } = useValues(membersLogic)
    const { setSearch } = useActions(membersLogic)

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
            render: (_, member) => member.user.email,
            sorter: (a, b) => a.user.email.localeCompare(b.user.email),
        },
        {
            title: 'Level',
            dataIndex: 'level',
            key: 'level',
            render: function LevelRender(_, member) {
                return (
                    <LemonTag data-attr="change-membership-level">
                        {member.level === OrganizationMembershipLevel.Owner
                            ? 'Organization owner'
                            : `Project ${membershipLevelToName.get(member.level) ?? `unknown (${member.level})`}`}
                    </LemonTag>
                )
            },
            sorter: (a, b) => a.level - b.level,
        },
        {
            title: 'Joined',
            dataIndex: 'joined_at',
            key: 'joined_at',
            render: function RenderJoinedAt(joinedAt) {
                return (
                    <div className="no-wrap">
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
            <h2 className="subtitle">Members</h2>
            <Input.Search
                placeholder="Search for members"
                allowClear
                enterButton
                style={{ maxWidth: 600, width: 'initial', flexGrow: 1, marginRight: 12 }}
                value={search}
                onChange={(e) => {
                    setSearch(e.target.value)
                }}
            />
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
