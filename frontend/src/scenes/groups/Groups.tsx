import { Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { ResizableColumnType, ResizableTable } from 'lib/components/ResizableTable'
import { capitalizeFirstLetter, humanFriendlyDetailedTime } from 'lib/utils'
import React from 'react'
import { groupsModel } from '~/models/groupsModel'
import { Group } from '~/types'

interface GroupsTableType {
    groups: Group[]
    groupType: string
}

export function Groups({ groups, groupType }: GroupsTableType): JSX.Element {
    const { setTab, loadGroupList } = useActions(groupsModel)
    const { groupTypes, groupsList } = useValues(groupsModel)

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
            <Tabs
                defaultActiveKey="1"
                onChange={(activeKey) => {
                    setTab(activeKey)
                    if (activeKey !== 'persons') {
                        loadGroupList(activeKey)
                    }
                }}
            >
                <Tabs.TabPane tab="Persons" key="persons" />
                {groupTypes.map((groupType) => (
                    <Tabs.TabPane tab={capitalizeFirstLetter(groupType.group_type)} key={groupType.group_type_index} />
                ))}
            </Tabs>
            <ResizableTable size="small" columns={columns} rowKey="id" dataSource={groupsList}></ResizableTable>
        </>
    )
}
