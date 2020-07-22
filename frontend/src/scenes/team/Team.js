import React, { useState } from 'react'
import { Card, Loading } from 'lib/utils'
import { InviteTeam } from 'lib/components/InviteTeam'
import { Table, Modal, Button, Row } from 'antd'
import { useValues, useActions } from 'kea'
import { teamLogic } from './teamLogic'
import { DeleteOutlined, ExclamationCircleOutlined } from '@ant-design/icons'

function Team({ user }) {
    const logic = teamLogic()
    const { users, usersLoading } = useValues(logic)
    const { deleteUser } = useActions(logic)
    const { confirm } = Modal
    const [inviteModalOpen, setInviteModalOpen] = useState(false)

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
            <div>
                <h1 className="page-header">Team</h1>
                <p style={{ maxWidth: 600 }}>
                    <i>This is you and all your teammates. Manage them from here.</i>
                </p>
                <Row style={{ marginBottom: 32 }}>
                    <Button type="primary" onClick={() => setInviteModalOpen(true)}>
                        + Invite Teammate
                    </Button>
                </Row>
                <Card>
                    {usersLoading ? (
                        <div className="loading-overlay mt-5">
                            <div />
                            <Loading />
                            <br />
                        </div>
                    ) : (
                        <div className="card-body">
                            <Table dataSource={userDataMarked} columns={columns} rowKey="distinct_id" />
                        </div>
                    )}
                </Card>
            </div>
            <Modal visible={inviteModalOpen} footer={null} onCancel={() => setInviteModalOpen(false)}>
                <InviteTeam user={user} />
            </Modal>
        </>
    )
}

export default Team
