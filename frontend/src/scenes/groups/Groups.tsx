import { Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { ResizableColumnType, ResizableTable } from 'lib/components/ResizableTable'
import { capitalizeFirstLetter, humanFriendlyDetailedTime } from 'lib/utils'
import React from 'react'
import { groupsModel } from '~/models/groupsModel'
import { Group } from '~/types'

export function Groups(): JSX.Element {
    const { setTab, loadGroupList } = useActions(groupsModel)
    const { groupTypes, groupList, currentGroup } = useValues(groupsModel)

    const columns: ResizableColumnType<Partial<Group>>[] = [
        {
            title: `${capitalizeFirstLetter(groupTypes[currentGroup]?.group_type || '')} ID`,
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
            <Tabs defaultActiveKey={currentGroup} onChange={(activeKey) => setTab(activeKey)}>
                <Tabs.TabPane tab="Persons" key="-1" />
                {groupTypes.map((groupType) => (
                    <Tabs.TabPane tab={capitalizeFirstLetter(groupType.group_type)} key={groupType.group_type_index} />
                ))}
            </Tabs>
            <ResizableTable size="small" columns={columns} rowKey="id" dataSource={groupList}></ResizableTable>
        </>
    )
}
