import React from 'react'
import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { ResizableColumnType, ResizableTable } from 'lib/components/ResizableTable'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { Group } from '~/types'
import { groupsListLogic } from './groupsListLogic'
import { GroupsTabs } from './GroupsTabs'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'
import { PropertiesTable } from 'lib/components/PropertiesTable'

export function Groups(): JSX.Element {
    const { groups, groupsLoading } = useValues(groupsListLogic)
    const { loadGroups } = useActions(groupsListLogic)

    const columns: ResizableColumnType<Partial<Group>>[] = [
        {
            title: 'Key',
            key: 'group_key',
            span: 8,
            render: function Render(group: Group) {
                return <>{group.group_key}</>
            },
        },
        {
            title: 'Last updated',
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
                expandable={{
                    expandedRowRender: function RenderPropertiesTable({ group_properties }) {
                        return <PropertiesTable properties={group_properties} />
                    },
                    rowExpandable: ({ group_properties }) =>
                        !!group_properties && Object.keys(group_properties).length > 0,
                }}
                pagination={false}
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
