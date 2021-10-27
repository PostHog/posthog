import { Col, Dropdown, Input, Menu, Row, Select, Table, Tabs, Radio } from 'antd'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { ObjectTags } from 'lib/components/ObjectTags'
import { deleteWithUndo, humanFriendlyDetailedTime } from 'lib/utils'
import React from 'react'
import { DashboardItemType, LayoutView, SavedInsightsTabs } from '~/types'
import { savedInsightsLogic } from './savedInsightsLogic'
import {
    StarOutlined,
    StarFilled,
    LeftOutlined,
    RightOutlined,
    UnorderedListOutlined,
    AppstoreFilled,
    EllipsisOutlined,
    ArrowDownOutlined,
    MenuOutlined,
    CaretDownFilled,
} from '@ant-design/icons'
import './SavedInsights.scss'
import { organizationLogic } from 'scenes/organizationLogic'
import { DashboardItem, displayMap, getDisplayedType } from 'scenes/dashboard/DashboardItem'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import '../insights/InsightHistoryPanel/InsightHistoryPanel.scss'
import dayjs from 'dayjs'

import { PageHeader } from 'lib/components/PageHeader'
import { SavedInsightsEmptyState } from 'scenes/insights/EmptyStates'
import { teamLogic } from '../teamLogic'
import {
    InsightsFunnelsIcon,
    InsightsLifecycleIcon,
    InsightsPathsIcon,
    InsightsRetentionIcon,
    InsightsSessionsIcon,
    InsightsStickinessIcon,
    InsightsTrendsIcon,
} from 'lib/components/icons'
import { SceneExport } from 'scenes/sceneTypes'

const { TabPane } = Tabs

interface InsightType {
    type: string
    description?: string
    icon?: JSX.Element
    inMenu: boolean
}

const insightTypes: InsightType[] = [
    { type: 'All types', inMenu: false },
    {
        type: 'Trends',
        description: 'Understand how users are spending their time in your product',
        icon: <InsightsTrendsIcon color="#747EA2" noBackground />,
        inMenu: true,
    },
    {
        type: 'Funnels',
        description: 'Visualize completion and dropoff between events',
        icon: <InsightsFunnelsIcon color="#747EA2" noBackground />,
        inMenu: true,
    },
    {
        type: 'Sessions',
        description: 'Understand how users are spending their time in your product',
        icon: <InsightsSessionsIcon color="#747EA2" noBackground />,
        inMenu: false,
    },
    {
        type: 'Retention',
        description: 'Visualize how many users return on subsequent days after a session',
        icon: <InsightsRetentionIcon color="#747EA2" noBackground />,
        inMenu: true,
    },
    {
        type: 'Paths',
        description: 'Understand how traffic is flowing through your product',
        icon: <InsightsPathsIcon color="#747EA2" noBackground />,
        inMenu: true,
    },
    {
        type: 'Stickiness',
        description: 'See how many days users performed an action within a timeframe',
        icon: <InsightsStickinessIcon color="#747EA2" noBackground />,
        inMenu: true,
    },
    {
        type: 'Lifecycle',
        description: 'See new, resurrected, returning, and dormant users',
        icon: <InsightsLifecycleIcon color="#747EA2" noBackground />,
        inMenu: true,
    },
]

export const scene: SceneExport = {
    component: SavedInsights,
    logic: savedInsightsLogic,
}

export function SavedInsights(): JSX.Element {
    const {
        loadInsights,
        updateFavoritedInsight,
        loadPaginatedInsights,
        renameInsight,
        duplicateInsight,
        addToDashboard,
        addGraph,
        setSavedInsightsFilters,
    } = useActions(savedInsightsLogic)
    const { insights, count, offset, nextResult, previousResult, insightsLoading, filters } =
        useValues(savedInsightsLogic)

    const { nameSortedDashboards } = useValues(dashboardsModel)
    const { hasDashboardCollaboration } = useValues(organizationLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { members } = useValues(membersLogic)
    const { tab, order, createdBy, layoutView, search, insightType, dateFrom, dateTo } = filters

    const pageLimit = 15
    const paginationCount = (): number => {
        if (!previousResult) {
            // no previous url means it's the first result set
            return 1
        }
        if (nextResult) {
            return offset - pageLimit
        }
        return count - (insights?.results.length || 0)
    }

    const columns = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function renderName(name: string, insight: DashboardItemType) {
                const link = displayMap[getDisplayedType(insight.filters)].link(insight)

                return (
                    <Col>
                        <Row>
                            <Link to={link} style={{ marginRight: 12 }}>
                                <strong>{name || `Insight #${insight.id}`}</strong>
                            </Link>
                            <div
                                style={{ cursor: 'pointer', width: 'fit-content' }}
                                onClick={() =>
                                    updateFavoritedInsight({ id: insight.id, favorited: !insight.favorited })
                                }
                            >
                                {insight.favorited ? (
                                    <StarFilled className="text-warning" />
                                ) : (
                                    <StarOutlined className="star-outlined" />
                                )}
                            </div>
                        </Row>
                        {hasDashboardCollaboration && (
                            <div className="text-muted-alt">{insight.description || 'No description provided'}</div>
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
            title: (
                <div
                    className="order-by"
                    onClick={() =>
                        setSavedInsightsFilters({ order: order === '-updated_at' ? 'updated_at' : '-updated_at' })
                    }
                >
                    Last modified{' '}
                    <div style={{ fontSize: 10, paddingLeft: 8 }}>
                        <ArrowDownOutlined />
                        <MenuOutlined />
                    </div>
                </div>
            ),
            dataIndex: 'updated_at',
            key: 'updated_at',
            render: function renderLastModified(updated_at: string) {
                return <span>{humanFriendlyDetailedTime(updated_at)}</span>
            },
        },
        {
            title: (
                <div
                    className="order-by"
                    onClick={() =>
                        setSavedInsightsFilters({ order: order === 'created_by' ? '-created_by' : 'created_by' })
                    }
                >
                    {normalizeColumnTitle('Created by')}
                </div>
            ),
            render: function Render(_: any, item: DashboardItemType) {
                return (
                    <Row style={{ alignItems: 'center', justifyContent: 'space-between' }}>
                        <div>{item.created_by ? item.created_by.first_name || item.created_by.email : '-'}</div>
                        <Dropdown
                            placement="bottomRight"
                            trigger={['click']}
                            overlayStyle={{ minWidth: 240, border: '1px solid var(--primary)' }}
                            overlay={
                                <Menu style={{ padding: '12px 4px' }} data-attr={`insight-${item.id}-dropdown-menu`}>
                                    {nameSortedDashboards.filter((d) => d.id !== item.id).length > 0 ? (
                                        <Menu.SubMenu
                                            data-attr={'insight-' + item.id + '-dropdown-move'}
                                            key="move"
                                            title="Add to dashboard"
                                        >
                                            {nameSortedDashboards
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
                                        data-attr={`insight-item-${item.id}-dropdown-rename`}
                                        title="Rename"
                                    >
                                        Rename
                                    </Menu.Item>
                                    <Menu.Item
                                        onClick={() => duplicateInsight(item)}
                                        data-attr={`insight-item-${item.id}-dropdown-duplicate`}
                                    >
                                        Duplicate
                                    </Menu.Item>
                                    <Menu.Item
                                        onClick={() =>
                                            deleteWithUndo({
                                                object: item,
                                                endpoint: `api/projects/${currentTeamId}/insights`,
                                                callback: loadInsights,
                                            })
                                        }
                                        style={{ color: 'var(--danger)' }}
                                        data-attr={`insight-item-${item.id}-dropdown-remove`}
                                    >
                                        Remove
                                    </Menu.Item>
                                </Menu>
                            }
                        >
                            <EllipsisOutlined
                                style={{ color: 'var(--primary)' }}
                                className="insight-dropdown-actions"
                            />
                        </Dropdown>
                    </Row>
                )
            },
        },
    ]

    return (
        <div className="saved-insights">
            <Row style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
                <PageHeader title={'Insights'} />
                <Dropdown
                    overlay={
                        <Menu className="saved-insights-menu">
                            {insightTypes
                                .filter((i) => i.inMenu)
                                .map((menuItem) => (
                                    <Menu.Item onClick={() => addGraph(menuItem.type)} key={menuItem.type}>
                                        <Row className="icon-menu">
                                            <Col>{menuItem.icon}</Col>
                                            <Col>
                                                <strong>{menuItem.type}</strong>
                                                <p>{menuItem.description}</p>
                                            </Col>
                                        </Row>
                                    </Menu.Item>
                                ))}
                        </Menu>
                    }
                    trigger={['click']}
                >
                    <button className="new-insight-dropdown-btn" onClick={(e) => e.preventDefault()}>
                        New Insight <CaretDownFilled style={{ paddingLeft: 12 }} />
                    </button>
                </Dropdown>
            </Row>

            <Tabs
                activeKey={tab}
                style={{ borderColor: '#D9D9D9' }}
                onChange={(t) => setSavedInsightsFilters({ tab: t as SavedInsightsTabs })}
            >
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
                        onChange={(e) => setSavedInsightsFilters({ search: e.target.value })}
                        value={search || ''}
                        onSearch={() => loadInsights()}
                    />
                </Col>
                <Col>
                    Type
                    <Select
                        value={insightType}
                        style={{ paddingLeft: 8, width: 120 }}
                        onChange={(it) => setSavedInsightsFilters({ insightType: it })}
                    >
                        {insightTypes.map((insight: InsightType, index) => (
                            <Select.Option key={index} value={insight.type}>
                                <div style={{ display: 'flex' }}>
                                    {insight.icon ? (
                                        <span
                                            style={{
                                                display: 'inline-block',
                                                marginTop: -6,
                                                marginBottom: -8,
                                                marginLeft: -5,
                                                marginRight: 3,
                                            }}
                                        >
                                            {insight.icon}
                                        </span>
                                    ) : null}
                                    <span>{insight.type}</span>
                                </div>
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
                            onChange={(fromDate, toDate) =>
                                setSavedInsightsFilters({ dateFrom: fromDate, dateTo: toDate })
                            }
                        />
                    </div>
                </Col>
                <Col>
                    Created by
                    <Select
                        value={createdBy}
                        style={{ paddingLeft: 8, width: 120 }}
                        onChange={(cb) => {
                            setSavedInsightsFilters({ createdBy: cb })
                        }}
                    >
                        <Select.Option value={'All users'}>All users</Select.Option>
                        {members.map((member) => (
                            <Select.Option key={member.user.id} value={member.user.id}>
                                {member.user.first_name}
                            </Select.Option>
                        ))}
                    </Select>
                </Col>
            </Row>
            {insights.count > 0 && (
                <Row className="list-or-card-layout">
                    Showing {paginationCount()} - {nextResult ? offset : count} of {count} insights
                    <div>
                        <Radio.Group
                            onChange={(e) => setSavedInsightsFilters({ layoutView: e.target.value })}
                            value={layoutView}
                            buttonStyle="solid"
                        >
                            <Radio.Button value={LayoutView.List}>
                                <UnorderedListOutlined className="mr-05" />
                                List
                            </Radio.Button>
                            <Radio.Button value={LayoutView.Card}>
                                <AppstoreFilled className="mr-05" />
                                Card
                            </Radio.Button>
                        </Radio.Group>
                    </div>
                </Row>
            )}
            {!insightsLoading && insights.count < 1 ? (
                <SavedInsightsEmptyState />
            ) : (
                <>
                    {layoutView === LayoutView.List ? (
                        <Table
                            loading={insightsLoading}
                            columns={columns}
                            dataSource={insights.results}
                            pagination={false}
                            rowKey="id"
                            footer={() => (
                                <Row className="footer-pagination">
                                    <span className="text-muted-alt">
                                        {insights.count > 0 &&
                                            `Showing ${paginationCount()} - ${
                                                nextResult ? offset : count
                                            } of ${count} insights`}
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
                                            loadDashboardItems={() => {
                                                loadInsights()
                                            }}
                                            dashboardMode={null}
                                            index={index}
                                            isOnEditMode={false}
                                            footer={
                                                <div className="dashboard-item-footer">
                                                    {
                                                        <>
                                                            Saved {dayjs(insight.created_at).fromNow()} by{' '}
                                                            {insight.created_by?.first_name ||
                                                                insight.created_by?.email ||
                                                                'unknown'}
                                                        </>
                                                    }
                                                </div>
                                            }
                                        />
                                    </Col>
                                ))}
                        </Row>
                    )}
                </>
            )}
        </div>
    )
}
