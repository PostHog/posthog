import React, { useCallback } from 'react'
import { Table, Modal, Button, Dropdown, Menu, Tooltip } from 'antd'
import { useValues, useActions } from 'kea'
import { membersLogic } from './logic'
import { DeleteOutlined, ExclamationCircleOutlined, LogoutOutlined, UpOutlined, DownOutlined } from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { hot } from 'react-hot-loader/root'
import { CreateOrgInviteModalWithButton } from '../Invites/CreateOrgInviteModal'
import { OrganizationMembershipLevel, organizationMembershipLevelToName } from 'lib/constants'
import { UserType } from '~/types'
import { ColumnsType } from 'antd/lib/table'
import { PageHeader } from 'lib/components/PageHeader'
import { organizationLogic } from 'scenes/organizationLogic'

interface MembersProps {
    user: UserType
}

export const Members = hot(_Members)
function _Members({ user }: MembersProps): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { members, membersLoading } = useValues(membersLogic)
    const { removeMember, changeMemberAccessLevel } = useActions(membersLogic)
    const { confirm } = Modal
    const LevelComponent = useCallback(
        (level: OrganizationMembershipLevel, member) => {
            const levelName = organizationMembershipLevelToName.get(level) ?? 'unknown'

            return (currentOrganization?.membership_level ?? -1) < OrganizationMembershipLevel.Admin ? (
                <Tooltip title="Only organization administrators can change access levels.">
                    <Button>{levelName}</Button>
                </Tooltip>
            ) : (currentOrganization?.membership_level ?? -1) < member.level ? (
                <Tooltip title="You can only change access level of users with level lower or equal to you.">
                    <Button>{levelName}</Button>
                </Tooltip>
            ) : member.user_id === user.id ? (
                <Tooltip title="You can't change your own access level.">
                    <Button>{levelName}</Button>
                </Tooltip>
            ) : (
                <Dropdown
                    overlay={
                        <Menu>
                            {Object.values(OrganizationMembershipLevel).map(
                                (listLevel) =>
                                    typeof listLevel === 'number' &&
                                    listLevel !== level &&
                                    listLevel <= (currentOrganization?.membership_level ?? -1) && (
                                        <Menu.Item key={`${member.user_id}-level-${level}`}>
                                            <a
                                                href="#"
                                                onClick={() => {
                                                    changeMemberAccessLevel({ member, level: listLevel })
                                                }}
                                            >
                                                {listLevel > level ? (
                                                    <>
                                                        <UpOutlined style={{ marginRight: '0.5rem' }} />
                                                        Promote to{' '}
                                                    </>
                                                ) : (
                                                    <>
                                                        <DownOutlined style={{ marginRight: '0.5rem' }} />
                                                        Demote to{' '}
                                                    </>
                                                )}
                                                {organizationMembershipLevelToName.get(listLevel)}
                                            </a>
                                        </Menu.Item>
                                    )
                            )}
                        </Menu>
                    }
                >
                    <Button>{levelName}</Button>
                </Dropdown>
            )
        },
        [user]
    )

    const ActionsComponent = useCallback(
        (_, member) => {
            function handleClick(): void {
                confirm({
                    title: `${
                        member.user_id == user.id ? 'Leave' : `Remove ${member.user_first_name} from`
                    } organization ${user.organization.name}?`,
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
                    <a className="text-danger" onClick={handleClick}>
                        {member.user_id !== user.id ? (
                            <DeleteOutlined title="Remove Member" />
                        ) : (
                            <LogoutOutlined title="Leave Organization" />
                        )}
                    </a>
                </div>
            )
        },
        [user]
    )

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
