import React from 'react'
import { Table, Modal, Button, Dropdown, Menu } from 'antd'
import { useValues, useActions } from 'kea'
import { membersLogic } from './membersLogic'
import {
    DeleteOutlined,
    ExclamationCircleOutlined,
    LogoutOutlined,
    UpOutlined,
    DownOutlined,
    SwapOutlined,
    CrownFilled,
} from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { OrganizationMembershipLevel } from 'lib/constants'
import { OrganizationMemberType, UserType } from '~/types'
import { ColumnsType } from 'antd/lib/table'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { Tooltip } from 'lib/components/Tooltip'
import {
    getReasonForAccessLevelChangeProhibition,
    organizationMembershipLevelIntegers,
    membershipLevelToName,
} from '../../../lib/utils/permissioning'

function LevelComponent(member: OrganizationMemberType): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { changeMemberAccessLevel } = useActions(membersLogic)

    const myMembershipLevel = currentOrganization ? currentOrganization.membership_level : null

    if (!user) {
        return null
    }

    function generateHandleClick(listLevel: OrganizationMembershipLevel): (event: React.MouseEvent) => void {
        return function handleClick(event: React.MouseEvent) {
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
        }
    }

    const levelButton = (
        <Button
            data-attr="change-membership-level"
            icon={member.level === OrganizationMembershipLevel.Owner ? <CrownFilled /> : undefined}
        >
            {membershipLevelToName.get(member.level) ?? `unknown (${member.level})`}
        </Button>
    )

    const allowedLevels = organizationMembershipLevelIntegers.filter(
        (listLevel) => !getReasonForAccessLevelChangeProhibition(myMembershipLevel, user, member, listLevel)
    )
    const disallowedReason = getReasonForAccessLevelChangeProhibition(myMembershipLevel, user, member, allowedLevels)

    return disallowedReason ? (
        <Tooltip title={disallowedReason}>{levelButton}</Tooltip>
    ) : (
        <Dropdown
            overlay={
                <Menu>
                    {allowedLevels.map((listLevel) => (
                        <Menu.Item key={`${member.user.uuid}-level-${listLevel}`}>
                            <a href="#" onClick={generateHandleClick(listLevel)} data-test-level={listLevel}>
                                {listLevel === OrganizationMembershipLevel.Owner ? (
                                    <>
                                        <CrownFilled style={{ marginRight: '0.5rem' }} />
                                        Transfer organization ownership
                                    </>
                                ) : listLevel > member.level ? (
                                    <>
                                        <UpOutlined style={{ marginRight: '0.5rem' }} />
                                        Upgrade to {membershipLevelToName.get(listLevel)}
                                    </>
                                ) : (
                                    <>
                                        <DownOutlined style={{ marginRight: '0.5rem' }} />
                                        Downgrade to {membershipLevelToName.get(listLevel)}
                                    </>
                                )}
                            </a>
                        </Menu.Item>
                    ))}
                </Menu>
            }
        >
            {levelButton}
        </Dropdown>
    )
}

function ActionsComponent(member: OrganizationMemberType): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { removeMember } = useActions(membersLogic)

    if (!user) {
        return null
    }

    const currentMembershipLevel = currentOrganization?.membership_level ?? -1

    function handleClick(): void {
        if (!user) {
            throw Error
        }
        Modal.confirm({
            title: `${member.user.uuid == user.uuid ? 'Leave' : `Remove ${member.user.first_name} from`} organization ${
                user.organization?.name
            }?`,
            icon: <ExclamationCircleOutlined />,
            okText: member.user.uuid == user.uuid ? 'Leave' : 'Remove',
            okType: 'danger',
            cancelText: 'Cancel',
            onOk() {
                removeMember(member)
            },
        })
    }

    const allowDeletion =
        // higher-ranked users cannot be removed, at the same time the currently logged-in user can leave any time
        ((currentMembershipLevel >= OrganizationMembershipLevel.Admin && member.level <= currentMembershipLevel) ||
            member.user.uuid === user.uuid) &&
        // unless that user is the organization's owner, in which case they can't leave
        member.level !== OrganizationMembershipLevel.Owner

    return (
        <div>
            {allowDeletion && (
                <a className="text-danger" onClick={handleClick} data-attr="delete-org-membership">
                    {member.user.uuid !== user.uuid ? (
                        <DeleteOutlined title="Remove from organization" />
                    ) : (
                        <LogoutOutlined title="Leave organization" />
                    )}
                </a>
            )}
        </div>
    )
}

export interface MembersProps {
    /** Currently logged-in user. */
    user: UserType
}

export function Members({ user }: MembersProps): JSX.Element {
    const { members, membersLoading } = useValues(membersLogic)

    const columns: ColumnsType<OrganizationMemberType> = [
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
                return LevelComponent(member)
            },
            sorter: (a, b) => a.level - b.level,
            defaultSortOrder: 'descend',
        },
        {
            title: 'Joined At',
            dataIndex: 'joined_at',
            key: 'joined_at',
            render: (joinedAt: string) => humanFriendlyDetailedTime(joinedAt),
            sorter: (a, b) => a.joined_at.localeCompare(b.joined_at),
            defaultSortOrder: 'ascend',
        },
        {
            dataIndex: 'actions',
            key: 'actions',
            align: 'center',
            render: function ActionsRender(_, member) {
                return ActionsComponent(member)
            },
        },
    ]

    return (
        <>
            <h2 className="subtitle">Members</h2>
            <Table
                dataSource={members}
                columns={columns}
                rowKey="id"
                pagination={false}
                style={{ marginTop: '1rem' }}
                loading={membersLoading}
                data-attr="org-members-table"
            />
        </>
    )
}
