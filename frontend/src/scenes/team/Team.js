import React from 'react'
import { Card, Loading } from 'lib/utils'
import { Table, Modal } from 'antd'
import { useValues, useActions } from 'kea'
import { teamLogic } from './teamLogic'
import { DeleteOutlined, ExclamationCircleOutlined } from '@ant-design/icons'

function Team() {
    const logic = teamLogic()
    const { users, usersLoading } = useValues(logic)
    const { deleteUser } = useActions(logic)
    const { confirm } = Modal

    const ActionsComponent = (_text, record) => {
        const handleClick = () => {
            confirm({
                title: 'Are you sure delete this user?',
                icon: <ExclamationCircleOutlined />,
                content: 'The user will be permanently deleted. This action cannot be undone.',
                okText: 'Yes',
                okType: 'danger',
                cancelText: 'No',
                onOk() {
                    deleteUser(record)
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
    }

    ActionsComponent.displayName = 'ActionsComponent'

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
            title: 'Actions',
            dataIndex: 'actions',
            key: 'actions',
            align: 'center',
            render: ActionsComponent,
        },
    ]

    return (
        <div>
            <h1 className="page-header">Team</h1>
            <p>This is the list of all the users with access to PostHog for your team.</p>
            <Card>
                {usersLoading && (
                    <div className="loading-overlay mt-5">
                        <div />
                        <Loading />
                        <br />
                    </div>
                )}
                {!usersLoading && (
                    <div className="card-body">
                        <Table dataSource={users.results} columns={columns} rowKey="distinct_id" />
                    </div>
                )}
            </Card>
        </div>
    )
}

export default Team
