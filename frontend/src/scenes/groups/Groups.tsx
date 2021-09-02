import { useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { ResizableColumnType, ResizableTable } from 'lib/components/ResizableTable'
import { humanFriendlyDetailedTime } from 'lib/utils'
import React from 'react'
import { urls } from 'scenes/sceneLogic'
import { Group } from '~/types'
import { PageHeader } from '../../lib/components/PageHeader'
import { groupsLogic } from './groupsLogic'

export function Groups(): JSX.Element {
    const { currentGroupType, groups } = useValues(groupsLogic)

    if (!currentGroupType) {
        return <></>
    }

    const columns: ResizableColumnType<Partial<Group>>[] = [
        {
            title: 'Group',
            key: 'id',
            span: 8,
            render: function Render(group: Group) {
                return (
                    <Link key={group.id} to={urls.group(currentGroupType, group.id)}>
                        {group.id}
                    </Link>
                )
            },
        },
        {
            title: 'Created at',
            key: 'id',
            span: 8,
            render: function Render(group: Group) {
                return <div>{humanFriendlyDetailedTime(group.created_at)}</div>
            },
        },
    ]

    return (
        <div style={{ marginBottom: 128 }}>
            <PageHeader
                title={
                    <>
                        Groups – <code>{currentGroupType}</code>
                    </>
                }
            />
            <ResizableTable
                size="small"
                columns={columns}
                rowKey="id"
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                dataSource={groups}
                className="persons-table"
            />
        </div>
    )
}
