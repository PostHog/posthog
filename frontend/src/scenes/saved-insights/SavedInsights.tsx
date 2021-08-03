import { Button, Col, Row, Table, Tabs } from 'antd'
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
import {
    StarOutlined,
    StarFilled,
    LeftOutlined,
    RightOutlined,
    UnorderedListOutlined,
    AppstoreFilled,
} from '@ant-design/icons'
import './SavedInsights.scss'
const { TabPane } = Tabs

export function SavedInsights(): JSX.Element {
    const { loadInsights, updateFavoritedInsight, loadPaginatedInsights } = useActions(savedInsightsLogic)
    const { insights, count, offset, nextResult, previousResult, insightsLoading } = useValues(savedInsightsLogic)
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
                        <Row>
                            <Link to={`/i/${short_id}`} style={{ marginRight: 12 }}>
                                <strong>{name || `Insight #${id}`}</strong>
                            </Link>
                            <div
                                style={{ cursor: 'pointer', width: 'fit-content' }}
                                onClick={() => updateFavoritedInsight({ id, favorited: !favorited })}
                            >
                                {favorited ? (
                                    <StarFilled className="text-warning" />
                                ) : (
                                    <StarOutlined className="star-outlined" />
                                )}
                            </div>
                        </Row>
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
        createdByColumn(insights?.results || []) as ColumnType<DashboardItemType>,
    ]

    return (
        <div className="saved-insights">
            <Tabs defaultActiveKey="1" style={{ borderColor: '#D9D9D9' }} onChange={(key) => loadInsights(key)}>
                <TabPane tab="All" key="all" />
                <TabPane tab="Your Insights" key="yours" />
                <TabPane tab="Favorites" key="favorites" />
                <TabPane tab="Updated Recently" key="recent" />
            </Tabs>
            <Row className="list-or-card-layout">
                Showing {!previousResult ? 1 : nextResult ? offset - 15 : count - (insights?.results.length || 0)} -{' '}
                {nextResult ? offset : count} of {count} insights
                <div>
                    <Button>
                        <UnorderedListOutlined />
                        List
                    </Button>
                    <Button>
                        <AppstoreFilled />
                        Card
                    </Button>
                </div>
            </Row>
            <Table
                loading={insightsLoading}
                columns={displayedColumns}
                dataSource={insights?.results || []}
                pagination={false}
                footer={() => (
                    <Row className="footer-pagination">
                        <span className="text-muted-alt">
                            Showing{' '}
                            {!previousResult ? 1 : nextResult ? offset - 15 : count - (insights?.results.length || 0)} -{' '}
                            {nextResult ? offset : count} of {count} insights
                        </span>
                        <LeftOutlined
                            style={{ paddingRight: 16 }}
                            className={`${!previousResult ? 'paginate-disabled' : ''}`}
                            onClick={() => {
                                loadPaginatedInsights(previousResult)
                            }}
                        />
                        <RightOutlined
                            className={`${!nextResult ? 'paginate-disabled' : ''}`}
                            onClick={() => {
                                loadPaginatedInsights(nextResult)
                            }}
                        />
                    </Row>
                )}
            />
        </div>
    )
}
