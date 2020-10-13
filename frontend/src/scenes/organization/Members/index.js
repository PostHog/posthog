import React, { useCallback, useState } from 'react'
import { Row, Spin, Button } from 'antd'
import { Table, Modal } from 'antd'
import { useValues, useActions } from 'kea'
import { membersLogic } from './logic'
import { DeleteOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { hot } from 'react-hot-loader/root'
import { CreateOrgInviteModal } from '../Invites/CreateOrgInviteModal'
import { organizationMembershipLevelToName } from 'lib/constants'

export const Members = hot(_Members)
function _Members({ user }) {
    const { members, membersLoading } = useValues(membersLogic)
    const { removeMember } = useActions(membersLogic)
    const [isCreateInviteModalVisible, setIsCreateInviteModalVisible] = useState(false)
    const { confirm } = Modal

    const ActionsComponent = useCallback(
        (_text, member) => {
            if (member.user_id == user.id) return null

            const handleClick = () => {
                confirm({
                    title: `Remove ${member.user_first_name} from organization ${user.organization.name}?`,
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
                        <DeleteOutlined />
                    </a>
                </div>
            )
        },
        [user]
    )

    const columns = [
        {
            title: 'Name',
            dataIndex: 'user_first_name',
            key: 'user_first_name',
            render: (firstName, member) => (member.user_id == user.id ? `${firstName} (me)` : firstName),
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
            render: (level) => organizationMembershipLevelToName.get(level) ?? 'unknown',
        },
        {
            title: 'Joined At',
            dataIndex: 'joined_at',
            key: 'joined_at',
            render: (joinedAt) => humanFriendlyDetailedTime(joinedAt),
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
            <h1 className="page-header">Organization Members - {user?.organization.name}</h1>
            <div style={{ maxWidth: 672 }}>
                <i>
                    <p>
                        View and manage all members of {user.organization.name} here. Build an even better product
                        together.
                    </p>
                </i>
            </div>
            <Button
                type="primary"
                onClick={() => {
                    setIsCreateInviteModalVisible(true)
                }}
            >
                + Create an Invite
            </Button>
            <CreateOrgInviteModal isVisible={isCreateInviteModalVisible} setIsVisible={setIsCreateInviteModalVisible} />
            <div style={{ marginTop: '1rem' }}>
                {membersLoading ? (
                    <Row justify="center">
                        <Spin />
                    </Row>
                ) : (
                    <Table dataSource={members} columns={columns} rowKey="membership_id" pagination={false} />
                )}
            </div>
        </>
    )
}
