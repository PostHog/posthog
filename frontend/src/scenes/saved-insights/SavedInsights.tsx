import { Button, Col, Dropdown, Input, Menu, Row, Select, Table, Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { ObjectTags } from 'lib/components/ObjectTags'
import { deleteWithUndo, humanFriendlyDetailedTime } from 'lib/utils'
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
    EllipsisOutlined,
} from '@ant-design/icons'
import './SavedInsights.scss'
import { organizationLogic } from 'scenes/organizationLogic'
import { DashboardItem, DisplayedType, displayMap } from 'scenes/dashboard/DashboardItem'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import '../insights/InsightHistoryPanel/InsightHistoryPanel.scss'
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
        renameInsight,
        duplicateInsight,
        addToDashboard,
        setDates,
    } = useActions(savedInsightsLogic)
    const {
        insights,
        count,
        offset,
        nextResult,
        previousResult,
        insightsLoading,
        layoutView,
        searchTerm,
        dates: { dateFrom, dateTo },
    } = useValues(savedInsightsLogic)
    const { dashboards } = useValues(dashboardsModel)
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
            render: function Render(_: any, item: DashboardItemType) {
                return (
                    <Row style={{ alignItems: 'center' }}>
                        <div style={{ maxWidth: 250, width: 'auto', paddingRight: 16 }}>
                            {item.created_by ? item.created_by.first_name || item.created_by.email : '-'}
                        </div>
                        <Dropdown
                            placement="bottomRight"
                            trigger={['click']}
                            overlay={
                                <Menu style={{ padding: '12px 4px' }} data-attr={`insight-${item.id}-dropdown-menu`}>
                                    {dashboards.filter((d) => d.id !== item.id).length > 0 ? (
                                        <Menu.SubMenu
                                            data-attr={'insight-' + item.id + '-dropdown-move'}
                                            key="move"
                                            title="Add to dashboard"
                                        >
                                            {dashboards
                                                .filter((d) => d.id !== item.id)
                                                .map((dashboard, moveIndex) => (
                                                    <Menu.Item
                                                        data-attr={`insight-item-${item.id}-dropdown-move-${moveIndex}`}
                                                        key={dashboard.id}
                                                        onClick={() => addToDashboard(item, dashboard.id)}
                                                    >
                                                        {dashboard.name}
                                                    </Menu.Item>
                                                ))}
                                        </Menu.SubMenu>
                                    ) : null}
                                    <Menu.Item
                                        onClick={() => renameInsight(item.id)}
                                        style={{ padding: 8 }}
                                        data-attr={`insight-item-${item.id}-dropdown-rename`}
                                    >
                                        Rename
                                    </Menu.Item>
                                    <Menu.Item
                                        onClick={() => duplicateInsight(item)}
                                        style={{ padding: 8 }}
                                        data-attr={`insight-item-${item.id}-dropdown-duplicate`}
                                    >
                                        Duplicate
                                    </Menu.Item>
                                    <Menu.Item
                                        onClick={() =>
                                            deleteWithUndo({
                                                object: item,
                                                endpoint: 'insight',
                                                callback: loadInsights,
                                            })
                                        }
                                        style={{ padding: 8, color: 'var(--danger)' }}
                                        data-attr={`insight-item-${item.id}-dropdown-remove`}
                                    >
                                        Remove
                                    </Menu.Item>
                                </Menu>
                            }
                        >
                            <EllipsisOutlined className="insight-dropdown-actions" />
                        </Dropdown>
                    </Row>
                )
            },
            sorter: (a: Record<string, any>, b: Record<string, any>) =>
                (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
                    b.created_by?.first_name || b.created_by?.email || ''
                ),
        },
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
                    <div>
                        <span style={{ paddingRight: 8 }}>Last modified</span>
                        <DateFilter
                            defaultValue="All time"
                            disabled={false}
                            bordered={true}
                            dateFrom={dateFrom}
                            dateTo={dateTo}
                            onChange={setDates}
                        />
                    </div>
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
                                    dashboardMode={null}
                                    onClick={() => {
                                        const _type: DisplayedType =
                                            insight.filters.insight === ViewType.RETENTION
                                                ? 'RetentionContainer'
                                                : insight.filters.display
                                        window.open(displayMap[_type].link(insight))
                                    }}
                                    preventLoading={true}
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
