import React, { useEffect, useState } from 'react'
import { Button, Table } from 'antd'
import api from 'lib/api'
import { Link } from 'react-router-dom'
import { FilterLink } from '../../lib/components/FilterLink'
import { DeleteOutlined } from '@ant-design/icons'

import { toast } from 'react-toastify'

function Properties({ properties }) {
    return (
        <div className="d-flex flex-wrap flex-column" style={{ maxHeight: 200 }}>
            {Object.keys(properties)
                .sort()
                .map(key => (
                    <div
                        style={{
                            flex: '0 1',
                        }}
                        key={key}
                    >
                        <strong>{key}:</strong> {properties[key]}
                    </div>
                ))}
        </div>
    )
}

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
                    className="float-right"
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
                expandedRowRender: ({ properties }) => <Properties properties={properties} />,
                rowExpandable: ({ properties }) => Object.keys(properties).length > 0,
            }}
            dataSource={people}
        />
    )
}
