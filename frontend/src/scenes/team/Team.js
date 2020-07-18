import React from 'react'
import { Card, Loading } from 'lib/utils'
import { Table } from 'antd'
import { useValues } from 'kea'
import { teamLogic } from './teamLogic'

function Team() {
    const logic = teamLogic()
    const { users, usersLoading } = useValues(logic)

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
        },
    ]

    return (
        <div>
            <h1 className="page-header">Team</h1>
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
