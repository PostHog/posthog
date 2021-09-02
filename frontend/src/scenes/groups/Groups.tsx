import { useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { ResizableColumnType } from 'lib/components/ResizableTable'
import { capitalizeFirstLetter, humanFriendlyDetailedTime } from 'lib/utils'
import React from 'react'
import { urls } from 'scenes/sceneLogic'
import { Group } from '~/types'
import { groupsLogic } from './groupsLogic'
import { GroupsTable } from './GroupsTable'

export function Groups(): JSX.Element {
    const { currentGroupType } = useValues(groupsLogic)

    const columns: ResizableColumnType<Partial<Group>>[] = [
        {
            title: 'Group',
            key: 'id',
            span: 8,
            render: function Render(group: Group) {
                return (
                    <>
                        {currentGroupType ? (
                            <Link key={group.id} to={urls.group(currentGroupType, group.id)}>
                                {capitalizeFirstLetter(group.id)}
                            </Link>
                        ) : null}
                    </>
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

    return <div style={{ marginBottom: 128 }}>{currentGroupType ? <GroupsTable columns={columns} /> : null}</div>
}
