import React from 'react'
import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { ResizableColumnType, ResizableTable } from 'lib/components/ResizableTable'
import { capitalizeFirstLetter, humanFriendlyDetailedTime } from 'lib/utils'
import { groupsModel } from '~/models/groupsModel'
import { Group } from '~/types'
import { groupsListLogic } from './groupsListLogic'
import { GroupsTabs } from './GroupsTabs'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'

export function Groups(): JSX.Element {
    const { groups, currentGroup, groupsLoading } = useValues(groupsListLogic)
    const { loadGroups } = useActions(groupsListLogic)
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
                loading={groupsLoading}
                dataSource={groups.results}
            />
            {(groups.previous_url || groups.next_url) && (
                <div style={{ margin: '3rem auto 10rem', width: 200, display: 'flex', alignItems: 'center' }}>
                    <Button
                        type="link"
                        disabled={!groups.previous_url}
                        onClick={() => {
                            loadGroups(groups.previous_url)
                            window.scrollTo(0, 0)
                        }}
                    >
                        <LeftOutlined /> Previous
                    </Button>
                    <Button
                        type="link"
                        disabled={!groups.next_url}
                        onClick={() => {
                            loadGroups(groups.next_url)
                            window.scrollTo(0, 0)
                        }}
                    >
                        Next <RightOutlined />
                    </Button>
                </div>
            )}
        </>
    )
}
