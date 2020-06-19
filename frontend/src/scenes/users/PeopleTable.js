import React from 'react'
import { Button, Table } from 'antd'
import { Link } from 'lib/components/Link'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { DeleteOutlined } from '@ant-design/icons'
import { deletePersonData } from 'lib/utils'

export function PeopleTable({ people, loading, actions, onChange }) {
    let columns = [
        {
            title: 'Person',
            dataIndex: 'name',
            key: 'name',
            render: function RenderName(_, person) {
                return (
                    <Link to={'/person/' + encodeURIComponent(person.distinct_ids[0])} className="ph-no-capture">
                        {person.name}
                    </Link>
                )
            },
        },
    ]
    if (actions)
        columns.push({
            title: 'Actions',
            render: function RenderActions(person) {
                return (
                    <Button danger type="link" onClick={() => deletePersonData(person, onChange)}>
                        <DeleteOutlined />
                    </Button>
                )
            },
        })

    return (
        <Table
            size="small"
            columns={columns}
            loading={loading}
            rowKey={person => person.id}
            pagination={{ pageSize: 99999, hideOnSinglePage: true }}
            expandable={{
                expandedRowRender: function RenderPropertiesTable({ properties }) {
                    return <PropertiesTable properties={properties} />
                },
                rowExpandable: ({ properties }) => Object.keys(properties).length > 0,
            }}
            dataSource={people}
        />
    )
}
