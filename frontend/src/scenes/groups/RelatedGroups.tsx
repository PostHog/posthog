import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import Skeleton from 'antd/lib/skeleton'
import { groupsLogic } from 'scenes/groups/groupsLogic'
import { Link } from 'lib/components/Link'
import { Table } from 'antd'

export function RelatedGroups(): JSX.Element {
    const { relatedGroups, relatedGroupsLoading } = useValues(groupsLogic)
    const { loadRelatedGroups } = useActions(groupsLogic)

    useEffect(() => {
        if (relatedGroups === null && !relatedGroupsLoading) {
            loadRelatedGroups()
        }
    }, [relatedGroups, relatedGroupsLoading])

    if (relatedGroupsLoading) {
        return <Skeleton paragraph={{ rows: 2 }} active />
    }

    const columns = [
        {
            title: 'Type',
            dataIndex: 'type_key',
            key: 'type_key',
            className: 'ph-no-capture',
        },
        {
            title: 'Link',
            render: function RenderCount(_: any, group: any) {
                if (group.type_id == -1) {
                    return (
                        <Link to={`/person/${group.key}`} target="_blank">
                            {group.key}
                        </Link>
                    )
                } else {
                    return (
                        <Link to={`/groups/${group.type_key}/${group.key}`} target="_blank">
                            {group.key}
                        </Link>
                    )
                }
            },
        },
    ]

    return (
        <Table
            dataSource={relatedGroups || []}
            columns={columns}
            rowClassName="cursor-pointer"
            rowKey="id"
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
            locale={{ emptyText: 'No related groups' }}
        />
    )
}
