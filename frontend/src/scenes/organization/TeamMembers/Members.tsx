import React from 'react'
import { Table, Modal, Button, Dropdown, Menu, Tooltip } from 'antd'
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
import { OrganizationMembershipLevel, organizationMembershipLevelToName } from 'lib/constants'
import { OrganizationMemberType, OrganizationType, UserType } from '~/types'
import { ColumnsType } from 'antd/lib/table'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

const membershipLevelIntegers = Object.values(OrganizationMembershipLevel).filter(
    (value) => typeof value === 'number'
) as OrganizationMembershipLevel[]

function isMembershipLevelChangeDisallowed(
    currentOrganization: OrganizationType | null,
    currentUser: UserType,
    memberChanged: OrganizationMemberType,
    newLevelOrAllowedLevels: OrganizationMembershipLevel | OrganizationMembershipLevel[]
): false | string {
    const currentMembershipLevel = currentOrganization?.membership_level
    if (memberChanged.user_id === currentUser.id) {
        return "You can't change your own access level."
    }
    if (!currentMembershipLevel) {
        return 'Your membership level is unknown.'
    }
    if (Array.isArray(newLevelOrAllowedLevels)) {
        if (currentMembershipLevel === OrganizationMembershipLevel.Owner) {
            return false
        }
        if (!newLevelOrAllowedLevels.length) {
            return "You don't have permission to change this member's access level."
        }
    } else {
        if (newLevelOrAllowedLevels === memberChanged.level) {
            return "It doesn't make sense to set the same level as before."
        }
        if (currentMembershipLevel === OrganizationMembershipLevel.Owner) {
            return false
        }
        if (newLevelOrAllowedLevels > currentMembershipLevel) {
            return 'You can only change access level of others to lower or equal to your current one.'
        }
    }
    if (currentMembershipLevel < OrganizationMembershipLevel.Admin) {
        return "You don't have permission to change access levels."
    }
    if (currentMembershipLevel < memberChanged.level) {
        return 'You can only change access level of members with level lower or equal to you.'
    }
    return false
}

function LevelComponent(level: OrganizationMembershipLevel, member: OrganizationMemberType): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { changeMemberAccessLevel } = useActions(membersLogic)

    if (!user) {
        return null
    }

    function generateHandleClick(listLevel: OrganizationMembershipLevel): () => void {
        return function handleClick() {
            if (!user) {
                throw Error
            }
            if (listLevel === OrganizationMembershipLevel.Owner) {
                Modal.confirm({
                    centered: true,
                    title: `Pass on organization ownership to ${member.user_first_name}?`,
                    content: `You won't be ${user.organization?.name} owner anymore - you'll become just an administrator.`,
                    icon: <SwapOutlined />,
                    okType: 'danger',
                    okText: 'Pass Ownership',
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
        <Button icon={level === OrganizationMembershipLevel.Owner ? <CrownFilled /> : undefined}>
            {organizationMembershipLevelToName.get(level) ?? 'unknown'}
        </Button>
    )

    const allowedLevels = membershipLevelIntegers.filter(
        (listLevel) => !isMembershipLevelChangeDisallowed(currentOrganization, user, member, listLevel)
    )
    const disallowedReason = isMembershipLevelChangeDisallowed(currentOrganization, user, member, allowedLevels)

    return disallowedReason ? (
        <Tooltip title={disallowedReason}>{levelButton}</Tooltip>
    ) : (
        <Dropdown
            overlay={
                <Menu>
                    {allowedLevels.map((listLevel) => (
                        <Menu.Item key={`${member.user_id}-level-${listLevel}`}>
                            <a href="#" onClick={generateHandleClick(listLevel)}>
                                {listLevel === OrganizationMembershipLevel.Owner ? (
                                    <>
                                        <CrownFilled style={{ marginRight: '0.5rem' }} />
                                        Pass on organization ownership
                                    </>
                                ) : listLevel > level ? (
                                    <>
                                        <UpOutlined style={{ marginRight: '0.5rem' }} />
                                        Promote to {organizationMembershipLevelToName.get(listLevel)}
                                    </>
                                ) : (
                                    <>
                                        <DownOutlined style={{ marginRight: '0.5rem' }} />
                                        Demote to {organizationMembershipLevelToName.get(listLevel)}
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

function ActionsComponent(_, member: OrganizationMemberType): JSX.Element | null {
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
            title: `${member.user_id == user.id ? 'Leave' : `Remove ${member.user_first_name} from`} organization ${
                user.organization?.name
            }?`,
            icon: <ExclamationCircleOutlined />,
            okText: member.user_id == user.id ? 'Leave' : 'Remove',
            okType: 'danger',
            cancelText: 'Cancel',
            onOk() {
                removeMember(member)
                if (member.user_id == user.id) {
                    location.reload()
                }
            },
        })
    }

    const allowDeletion =
        // higher-ranked users cannot be removed, at the same time the currently logged-in user can leave any time
        (member.level <= currentMembershipLevel || member.user_id === user.id) &&
        // unless that user is the organization's owner, in which case they can't leave
        member.level !== OrganizationMembershipLevel.Owner

    return (
        <div>
            {allowDeletion && (
                <a className="text-danger" onClick={handleClick}>
                    {member.user_id !== user.id ? (
                        <DeleteOutlined title="Remove Member" />
                    ) : (
                        <LogoutOutlined title="Leave Organization" />
                    )}
                </a>
            )}
        </div>
    )
}

export function Members({ user }: { user: UserType }): JSX.Element {
    const { members, membersLoading } = useValues(membersLogic)

    const columns: ColumnsType<Record<string, any>> = [
        {
            title: 'Name',
            dataIndex: 'user_first_name',
            key: 'user_first_name',
            render: (firstName: string, member: Record<string, any>) =>
                member.user_id == user.id ? `${firstName} (me)` : firstName,
        },
        {
            title: 'Email',
            dataIndex: 'user_email',
            key: 'user_email',
        },
        {
            title: 'Level',
            dataIndex: 'level',
            key: 'level',
            render: LevelComponent,
        },
        {
            title: 'Joined At',
            dataIndex: 'joined_at',
            key: 'joined_at',
            render: (joinedAt: string) => humanFriendlyDetailedTime(joinedAt),
        },
        {
            title: '',
            dataIndex: 'actions',
            key: 'actions',
            align: 'center',
            render: ActionsComponent,
        },
    ]

    return (
        <>
            <h2 className="subtitle">Organization Members</h2>
            <Table
                dataSource={members}
                columns={columns}
                rowKey="membership_id"
                pagination={false}
                style={{ marginTop: '1rem' }}
                loading={membersLoading}
            />
        </>
    )
}
