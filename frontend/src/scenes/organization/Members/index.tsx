import React, { useCallback } from 'react'
import { Table, Modal } from 'antd'
import { useValues, useActions } from 'kea'
import { membersLogic } from './logic'
import { DeleteOutlined, ExclamationCircleOutlined, LogoutOutlined } from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { hot } from 'react-hot-loader/root'
import { CreateOrgInviteModalWithButton } from '../Invites/CreateOrgInviteModal'
import { OrganizationMembershipLevel, organizationMembershipLevelToName } from 'lib/constants'
import { UserType } from '~/types'
import { ColumnsType } from 'antd/lib/table'
import { PageHeader } from 'lib/components/PageHeader'

interface MembersProps {
    user: UserType
}

export const Members = hot(_Members)
function _Members({ user }: MembersProps): JSX.Element {
    const { members, membersLoading } = useValues(membersLogic)
    const { removeMember } = useActions(membersLogic)
    const { confirm } = Modal

    const ActionsComponent = useCallback(
        (_text, member) => {
            function handleClick(): void {
                confirm({
                    title: `${
                        member.user_id == user.id ? 'Leave' : `Remove ${member.user_first_name} from`
                    } organization ${user.organization.name}?`,
                    icon: <ExclamationCircleOutlined />,
                    okText: 'Delete',
                    okType: 'danger',
                    cancelText: 'Cancel',
                    onOk() {
                        removeMember(member)
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
            render: (level: OrganizationMembershipLevel) => organizationMembershipLevelToName.get(level) ?? 'unknown',
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
