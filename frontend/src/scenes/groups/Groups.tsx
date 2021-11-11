import { Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { ResizableColumnType, ResizableTable } from 'lib/components/ResizableTable'
import { capitalizeFirstLetter, humanFriendlyDetailedTime } from 'lib/utils'
import React, { useEffect } from 'react'
import { groupsModel } from '~/models/groupsModel'
import { Group } from '~/types'
import { groupsListLogic } from './groupsListLogic'
import { GroupsTabs } from './GroupsTabs'

export function Groups(): JSX.Element {
    const { groupList, currentGroup, groupListLoading } = useValues(groupsListLogic)
    const { groupTypes } = useValues(groupsModel)

    const columns: ResizableColumnType<Partial<Group>>[] = [
        {
            title: `${capitalizeFirstLetter(groupTypes[currentGroup]?.group_type || '')} Key`,
            key: 'group_key',
            span: 8,
            render: function Render(group: Group) {
                return <>{group.group_key}</>
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
            <GroupsTabs />
            <ResizableTable
                size="small"
                columns={columns}
                rowKey="group_key"
                loading={groupListLoading}
                dataSource={groupList}
            ></ResizableTable>
        </>
    )
}
