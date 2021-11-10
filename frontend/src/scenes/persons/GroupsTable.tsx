import { Link } from 'lib/components/Link'
import { ResizableColumnType, ResizableTable } from 'lib/components/ResizableTable'
import { capitalizeFirstLetter, humanFriendlyDetailedTime } from 'lib/utils'
import React from 'react'
import { Group } from '~/types'

interface GroupsTableType {
    groups: Group[]
    groupType: string
}

export function GroupsTable({ groups, groupType }: GroupsTableType): JSX.Element {
    const columns: ResizableColumnType<Partial<Group>>[] = [
        {
            title: `${capitalizeFirstLetter(groupType || '')} ID`,
            key: 'group_key',
            span: 8,
            render: function Render(group: Group) {
                return (
                    <>
                        {group.group_key}
                        {/* {groupType ? (

                            <Link key={group.id} to={urls.group(groupType, group.id)}>
                                {capitalizeFirstLetter(group.id)}
                            </Link>
                        ) : null} */}
                    </>
                )
            },
        },
        {
            title: 'Created at',
            key: 'created_at',
            span: 8,
            render: function Render(group: Group) {
                return <div>{humanFriendlyDetailedTime(group.created_at)}</div>
            },
        },
    ]

    return (
        <>
            <ResizableTable size="small" columns={columns} rowKey="id" dataSource={groups}></ResizableTable>
        </>
    )
}
