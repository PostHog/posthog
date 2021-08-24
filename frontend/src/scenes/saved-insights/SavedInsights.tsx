import { Button, Col, Dropdown, Menu, Row, Table, Tabs } from 'antd'
import { ColumnType } from 'antd/lib/table'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { ObjectTags } from 'lib/components/ObjectTags'
import { createdByColumn } from 'lib/components/Table/Table'
import { humanFriendlyDetailedTime } from 'lib/utils'
import React from 'react'
import { DashboardItemType, SavedInsightsParamOptions } from '~/types'
import { savedInsightsLogic } from './savedInsightsLogic'
import {
    StarOutlined,
    StarFilled,
    LeftOutlined,
    RightOutlined,
    UnorderedListOutlined,
    AppstoreFilled,
    CaretDownFilled,
} from '@ant-design/icons'
import './SavedInsights.scss'
import { organizationLogic } from 'scenes/organizationLogic'
import { PageHeader } from 'lib/components/PageHeader'
const { TabPane } = Tabs

export function SavedInsights(): JSX.Element {
    const { loadInsights, updateFavoritedInsight, loadPaginatedInsights, addGraph } = useActions(savedInsightsLogic)
    const { insights, count, offset, nextResult, previousResult, insightsLoading } = useValues(savedInsightsLogic)
    const { hasDashboardCollaboration } = useValues(organizationLogic)
    
    interface InsightItem {
        type: string 
        description: string
    }

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
        hasDashboardCollaboration
            ? {
                  title: 'Tags',
                  dataIndex: 'tags',
                  key: 'tags',
                  render: function renderTags(tags: string[]) {
                      return <ObjectTags tags={tags} staticOnly />
                  },
              }
            : {},
        {
            title: 'Last modified',
            dataIndex: 'updated_at',
            key: 'updated_at',
            render: function renderLastModified(updated_at: string) {
                return <span>{humanFriendlyDetailedTime(updated_at)}</span>
            },
            sorter: (a: DashboardItemType, b: DashboardItemType) =>
                new Date(a.updated_at) > new Date(b.updated_at) ? 1 : -1,
        },
        createdByColumn(insights.results) as ColumnType<DashboardItemType>,
    ]

    const menuItems: InsightItem[] = [
        { type: 'Trends', description: 'Visualize how actions or events are varying over time' },
        { type: 'Funnels', description: 'Visualize completion and dropoff between events' },
        { type: 'Sessions', description: 'Understand how users are spending their time in your product' },
        { type: 'Retention', description: 'Visualize how many users return on subsequent days after a session' },
        { type: 'User Paths', description: 'Understand how traffic is flowing through your product' },
        { type: 'Stickiness', description: 'See how many days users performed an action within a timeframe' },
        { type: 'Lifecycle', description: 'See new, resurrected, returning, and dormant users' },
    ]

    return (
        <div className="saved-insights">
            <Row style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
                <PageHeader style={{marginTop: 0 }} title={'Insights'} />
                <Dropdown
                    overlay={
                        <Menu style={{ maxWidth: 320, border: '1px solid var(--primary)' }}>
                            {menuItems.map((menuItem) => (
                                <Menu.Item onClick={({ key }) => addGraph(key)} style={{ margin: 8 }} key={menuItem.type}>
                                    <Col>
                                        <span style={{ fontWeight: 600 }}>{menuItem.type}</span>
                                        <p className="text-muted" style={{ whiteSpace: 'break-spaces' }}>
                                            {menuItem.description}
                                        </p>
                                    </Col>
                                </Menu.Item>
                            ))}
                        </Menu>
                    }
                    trigger={['click']}
                >
                    <a className="new-insight-dropdown-btn" onClick={(e) => e.preventDefault()}>
                        New Insight <CaretDownFilled style={{paddingLeft: 12}}/>
                    </a>
                </Dropdown>
            </Row>

            <Tabs defaultActiveKey="1" style={{ borderColor: '#D9D9D9' }} onChange={(key) => loadInsights(key)}>
                <TabPane tab="All Insights" key={SavedInsightsParamOptions.All} />
                <TabPane tab="Your Insights" key={SavedInsightsParamOptions.Yours} />
                <TabPane tab="Favorites" key={SavedInsightsParamOptions.Favorites} />
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
                columns={columns}
                dataSource={insights.results}
                pagination={false}
                rowKey="id"
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
                                previousResult && loadPaginatedInsights(previousResult)
                            }}
                        />
                        <RightOutlined
                            className={`${!nextResult ? 'paginate-disabled' : ''}`}
                            onClick={() => {
                                nextResult && loadPaginatedInsights(nextResult)
                            }}
                        />
                    </Row>
                )}
            />
        </div>
    )
}
