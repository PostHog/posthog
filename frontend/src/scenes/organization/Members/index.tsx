import React from 'react'
import { Table, Modal, Button, Dropdown, Menu, Tooltip } from 'antd'
import { useValues, useActions } from 'kea'
import { membersLogic } from './logic'
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
import { hot } from 'react-hot-loader/root'
import { CreateOrgInviteModalWithButton } from '../Invites/CreateOrgInviteModal'
import { OrganizationMembershipLevel, organizationMembershipLevelToName } from 'lib/constants'
import { OrganizationMemberType, OrganizationType, UserType } from '~/types'
import { ColumnsType } from 'antd/lib/table'
import { PageHeader } from 'lib/components/PageHeader'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

function isMembershipLevelChangeDisallowed(
    currentOrganization: OrganizationType | null,
    currentUser: UserType,
    memberChanged: OrganizationMemberType,
    newLevel?: OrganizationMembershipLevel
): false | string {
    const currentMembershipLevel = currentOrganization?.membership_level
    if (!currentMembershipLevel) return 'Your membership level is unknown.'
    if (newLevel) {
        if (newLevel >= currentMembershipLevel)
            return 'You can only change access level of others to lower than your current one.'
        if (newLevel === memberChanged.level) return "It doesn't make sense to set the same level as before."
    }
    return currentMembershipLevel < OrganizationMembershipLevel.Admin
        ? 'Only organization administrators can change access levels.'
        : currentMembershipLevel <= memberChanged.level
        ? 'You can only change access level of users with level lower than you.'
        : memberChanged.user_id === currentUser.id
        ? "You can't change your own access level."
        : false
}

function LevelComponent(level: OrganizationMembershipLevel, member: OrganizationMemberType): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { changeMemberAccessLevel } = useActions(membersLogic)

    if (!user) return null

    function generateHandleClick(listLevel: OrganizationMembershipLevel): () => void {
        return function handleClick() {
            if (!user) throw Error
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

    const disallowedReason = isMembershipLevelChangeDisallowed(currentOrganization, user, member)

    return disallowedReason ? (
        <Tooltip title={disallowedReason}>{levelButton}</Tooltip>
    ) : (
        <Dropdown
            overlay={
                <Menu>
                    {Object.values(OrganizationMembershipLevel).map(
                        (listLevel) =>
                            typeof listLevel === 'number' &&
                            !isMembershipLevelChangeDisallowed(currentOrganization, user, member, listLevel) && (
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
                            )
                    )}
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

    if (!user) return null

    const currentMembershipLevel = currentOrganization?.membership_level ?? -1

    function handleClick(): void {
        if (!user) throw Error
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
                if (member.user_id == user.id) location.reload()
            },
        })
    }

    return (
        <div>
            {member.level !== OrganizationMembershipLevel.Owner &&
                (member.level < currentMembershipLevel || member.user_id === user.id) && (
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

interface MembersProps {
    user: UserType
}

export const Members = hot(_Members)
function _Members({ user }: MembersProps): JSX.Element {
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
            <PageHeader
                title="Organization Members"
                caption="View and manage all organization members here. Build an even better product together."
            />
            <CreateOrgInviteModalWithButton />
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
