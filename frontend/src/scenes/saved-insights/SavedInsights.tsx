import { Button, Col, Input, Row, Select, Table, Tabs } from 'antd'
import { ColumnType } from 'antd/lib/table'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { ObjectTags } from 'lib/components/ObjectTags'
import { createdByColumn } from 'lib/components/Table/Table'
import { humanFriendlyDetailedTime } from 'lib/utils'
import React from 'react'
import { DashboardItemType, SavedInsightsTabs, ViewType } from '~/types'
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
import { organizationLogic } from 'scenes/organizationLogic'
import { DashboardItem, DisplayedType, displayMap } from 'scenes/dashboard/DashboardItem'
import { router } from 'kea-router'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
const { TabPane } = Tabs

export function SavedInsights(): JSX.Element {
    const {
        loadInsights,
        updateFavoritedInsight,
        loadPaginatedInsights,
        setLayoutView,
        setSearchTerm,
        setTab,
        setInsightType,
        setCreatedBy,
    } = useActions(savedInsightsLogic)
    const { insights, count, offset, nextResult, previousResult, insightsLoading, layoutView, searchTerm } = useValues(
        savedInsightsLogic
    )
    const { hasDashboardCollaboration } = useValues(organizationLogic)
    const insightTypes = ['All types', 'Trends', 'Funnels', 'Retention', 'Paths', 'Sessions', 'Stickiness', 'Lifecycle']
    const { members } = useValues(membersLogic)

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
        {
            title: normalizeColumnTitle('Created by'),
            render: function Render(_: any, item: any) {
                return (
                    <div style={{ maxWidth: 250, width: 'auto' }}>
                        {item.created_by ? item.created_by.first_name || item.created_by.email : '-'}
                    </div>
                )
            },
            sorter: (a: Record<string, any>, b: Record<string, any>) =>
                (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
                    b.created_by?.first_name || b.created_by?.email || ''
                ),
        },
        // createdByColumn(insights.results) as ColumnType<DashboardItemType>,
    ]

    return (
        <div className="saved-insights">
            <Tabs defaultActiveKey="1" style={{ borderColor: '#D9D9D9' }} onChange={(tab) => setTab(tab)}>
                <TabPane tab="All Insights" key={SavedInsightsTabs.All} />
                <TabPane tab="Your Insights" key={SavedInsightsTabs.Yours} />
                <TabPane tab="Favorites" key={SavedInsightsTabs.Favorites} />
            </Tabs>
            <Row style={{ paddingBottom: 16, justifyContent: 'space-between' }}>
                <Col>
                    <Input.Search
                        allowClear
                        enterButton
                        placeholder="Search for insights"
                        style={{ width: 240 }}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        value={searchTerm || ''}
                        onSearch={() => loadInsights()}
                    />
                </Col>
                <Col>
                    Type
                    <Select defaultValue="All types" style={{ paddingLeft: 8, width: 120 }} onChange={setInsightType}>
                        {insightTypes.map((type, index) => (
                            <Select.Option key={index} value={type}>
                                {type}
                            </Select.Option>
                        ))}
                    </Select>
                </Col>
                <Col>
                    Last modified
                    <Select defaultValue="All time" style={{ paddingLeft: 8, width: 120 }} onChange={() => {}}></Select>
                </Col>
                <Col>
                    Created by
                    <Select
                        defaultValue="All users"
                        style={{ paddingLeft: 8, width: 120 }}
                        onChange={(userId) => {
                            const createdBy = userId === 'All users' ? undefined : userId
                            setCreatedBy({ id: createdBy })
                        }}
                    >
                        <Select.Option value={'All users'}>All users</Select.Option>
                        {members.map((member) => (
                            <Select.Option key={member.user_id} value={member.user_id}>
                                {member.user_first_name}
                            </Select.Option>
                        ))}
                    </Select>
                </Col>
            </Row>
            <Row className="list-or-card-layout">
                Showing {!previousResult ? 1 : nextResult ? offset - 15 : count - (insights?.results.length || 0)} -{' '}
                {nextResult ? offset : count} of {count} insights
                <div>
                    <Button onClick={() => setLayoutView('list')}>
                        <UnorderedListOutlined />
                        List
                    </Button>
                    <Button onClick={() => setLayoutView('card')}>
                        <AppstoreFilled />
                        Card
                    </Button>
                </div>
            </Row>
            {layoutView === 'list' ? (
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
                                {!previousResult
                                    ? 1
                                    : nextResult
                                    ? offset - 15
                                    : count - (insights?.results.length || 0)}{' '}
                                - {nextResult ? offset : count} of {count} insights
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
            ) : (
                <Row gutter={[16, 16]}>
                    {insights &&
                        insights.results.map((insight: DashboardItemType, index: number) => (
                            <Col
                                xs={24}
                                sm={12}
                                md={insights.results.length > 1 ? 8 : 12}
                                key={insight.id}
                                style={{ height: 270 }}
                            >
                                <DashboardItem
                                    item={{ ...insight, color: null }}
                                    key={insight.id + '_user'}
                                    // saveDashboardItem={updateInsight}
                                    loadDashboardItems={() => {
                                        loadInsights()
                                        // loadSavedInsights()
                                        // loadTeamInsights()
                                    }}
                                    // saveDashboardItem={updateInsight}
                                    dashboardMode={null}
                                    onClick={() => {
                                        const _type: DisplayedType =
                                            insight.filters.insight === ViewType.RETENTION
                                                ? 'RetentionContainer'
                                                : insight.filters.display
                                        router.actions.push(displayMap[_type].link(insight))
                                    }}
                                    preventLoading={true}
                                    // footer={<div>ehh??</div>}
                                    index={index}
                                    isOnEditMode={false}
                                />
                            </Col>
                        ))}
                </Row>
            )}
        </div>
    )
}
