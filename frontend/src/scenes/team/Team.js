import React from 'react'
import { Row, Spin } from 'antd'
import { TeamInvitationContent } from 'lib/components/TeamInvitation'
import { Table, Modal } from 'antd'
import { useValues, useActions } from 'kea'
import { teamLogic } from './teamLogic'
import { DeleteOutlined, ExclamationCircleOutlined } from '@ant-design/icons'

function Team({ user }) {
    const logic = teamLogic()
    const { users, usersLoading } = useValues(logic)
    const { deleteUser } = useActions(logic)
    const { confirm } = Modal

    const ActionsComponent = (_text, record) => {
        const handleClick = () => {
            confirm({
                title: `Delete teammate ${record.first_name}?`,
                icon: <ExclamationCircleOutlined />,
                content: (
                    <>
                        Their PostHog account will be deleted.
                        <br />
                        This cannot be undone.
                    </>
                ),
                okText: 'Delete',
                okType: 'danger',
                cancelText: 'Cancel',
                onOk() {
                    deleteUser(record)
                },
            })
        }

        return (
            <div>
                {record.id !== user.id && (
                    <a className="text-danger" onClick={handleClick}>
                        <DeleteOutlined />
                    </a>
                )}
            </div>
        )
    }

    ActionsComponent.displayName = 'ActionsComponent'

    const userDataMarked = users?.results?.map((result) =>
        result.id === user.id ? { ...result, first_name: `${result.first_name} (you)` } : result
    )
    const columns = [
        {
            title: 'Name',
            dataIndex: 'first_name',
            key: 'first_name',
        },
        {
            title: 'Email',
            dataIndex: 'email',
            key: 'email',
        },
        /*{
            title: '',
            dataIndex: 'actions',
            key: 'actions',
            align: 'center',
            render: ActionsComponent,
        },*/
    ]

    return (
        <>
            <h1 className="page-header">Team</h1>
            <div style={{ maxWidth: 672 }}>
                <i>
                    <p>This is you and all your teammates. Manage them from here.</p>
                    <TeamInvitationContent user={user} />
                </i>
            </div>
            <div style={{ marginTop: '1rem' }}>
                {usersLoading ? (
                    <Row justify="center">
                        <Spin />
                    </Row>
                ) : (
                    <Table dataSource={userDataMarked} columns={columns} rowKey="distinct_id" />
                )}
            </div>
        </>
    )
}

export default Team
