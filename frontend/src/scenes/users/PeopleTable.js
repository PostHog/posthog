import React, { useEffect, useState } from 'react'
import { Button, Table } from 'antd'
import api from 'lib/api'
import { Link } from 'react-router-dom'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { DeleteOutlined } from '@ant-design/icons'

import { toast } from 'react-toastify'

export function PeopleTable({ people, loading, actions, onChange }) {
    let columns = [
        {
            title: 'Person',
            dataIndex: 'name',
            key: 'name',
            render: (_, person) => (
                <Link to={'/person/' + encodeURIComponent(person.distinct_ids[0])} className="ph-no-capture">
                    {person.name}
                </Link>
            ),
        },
        actions && {
            title: 'Actions',
            render: person => (
                <Button
                    danger
                    type="link"
                    onClick={() => {
                        window.confirm('Are you sure you want to delete this user? This cannot be undone') &&
                            api.delete('api/person/' + person.id).then(() => {
                                toast('Person succesfully deleted.')
                                onChange()
                            })
                    }}
                >
                    <DeleteOutlined />
                </Button>
            ),
        },
    ]
    return (
        <Table
            size="small"
            columns={columns}
            loading={loading}
            rowKey={person => person.id}
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
            expandable={{
                expandedRowRender: ({ properties }) => <PropertiesTable properties={properties} />,
                rowExpandable: ({ properties }) => Object.keys(properties).length > 0,
            }}
            dataSource={people}
        />
    )
}
