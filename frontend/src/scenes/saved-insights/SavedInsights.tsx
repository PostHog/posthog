import { Button, Col, Table, Tabs } from 'antd'
import { ColumnType } from 'antd/lib/table'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { ObjectTags } from 'lib/components/ObjectTags'
import { createdByColumn } from 'lib/components/Table/Table'
import { humanFriendlyDetailedTime } from 'lib/utils'
import React, { useEffect, useState } from 'react'
import { userLogic } from 'scenes/userLogic'
import { DashboardItemType } from '~/types'
import { savedInsightsLogic } from './savedInsightsLogic'
import { StarOutlined, StarFilled } from '@ant-design/icons'
const { TabPane } = Tabs

export function SavedInsights(): JSX.Element {
    const { loadInsights, updateFavoritedInsight } = useActions(savedInsightsLogic)
    const { insights } = useValues(savedInsightsLogic)
    const { hasDashboardCollaboration } = useValues(userLogic)
    const [displayedColumns, setDisplayedColumns] = useState([] as ColumnType<DashboardItemType>[])

    useEffect(() => {
        loadInsights()
    }, [])

    useEffect(() => {
        if (!hasDashboardCollaboration) {
            setDisplayedColumns(columns.filter((col) => !col.dataIndex || !['tags'].includes(col.dataIndex.toString())))
        } else {
            setDisplayedColumns(columns)
        }
    }, [hasDashboardCollaboration])

    const columns = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function renderName(
                name: string,
                {
                    short_id,
                    id,
                    description,
                    favorited,
                }: { short_id: string; id: number; description?: string; favorited?: boolean }
            ) {
                return (
                    <Col>
                        <div>
                            <Link to={`/i/${short_id}`} style={{ marginRight: 16 }}>
                                <strong>{name || `Insight #${id}`}</strong>
                            </Link>
                            <Button
                                onClick={() => updateFavoritedInsight({ id, favorited: !favorited })}
                                icon={favorited ? <StarFilled /> : <StarOutlined />}
                            />
                        </div>
                        {hasDashboardCollaboration && (
                            <div className="text-muted-alt">{description || 'No description provided'}</div>
                        )}
                    </Col>
                )
            },
        },
        {
            title: 'Tags',
            dataIndex: 'tags',
            key: 'tags',
            render: function renderTags(tags: string[]) {
                return <ObjectTags tags={tags} staticOnly />
            },
        },
        {
            title: 'Last modified',
            dataIndex: 'updated_at',
            key: 'updated_at',
            render: function renderLastModified(updated_at: string) {
                return <span>{humanFriendlyDetailedTime(updated_at)}</span>
            },
            sorter: (a: DashboardItemType, b: DashboardItemType) =>
                new Date(a.created_at) > new Date(b.created_at) ? 1 : -1,
        },
        createdByColumn(insights) as ColumnType<DashboardItemType>,
    ]

    return (
        <>
            <Tabs defaultActiveKey="1" onChange={(key) => loadInsights(key)}>
                <TabPane tab="All" key="all" />
                <TabPane tab="Your Insights" key="yours" />
                <TabPane tab="Favorites" key="favorites" />
                <TabPane tab="Updated Recently" key="recent" />
            </Tabs>
            <Table columns={displayedColumns} dataSource={insights} />
        </>
    )
}
