import { Col, Dropdown, Input, Menu, Radio, Row, Select, Tabs } from 'antd'
import { router } from 'kea-router'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { ObjectTags } from 'lib/components/ObjectTags'
import { deleteWithUndo } from 'lib/utils'
import React from 'react'
import { DashboardItemType, InsightType, LayoutView, SavedInsightsTabs } from '~/types'
import { INSIGHTS_PER_PAGE, savedInsightsLogic } from './savedInsightsLogic'
import { AppstoreFilled, StarFilled, StarOutlined, PlusOutlined, UnorderedListOutlined } from '@ant-design/icons'
import './SavedInsights.scss'
import { organizationLogic } from 'scenes/organizationLogic'
import { DashboardItem } from 'scenes/dashboard/DashboardItem'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PageHeader } from 'lib/components/PageHeader'
import { SavedInsightsEmptyState, UNNAMED_INSIGHT_NAME } from 'scenes/insights/EmptyStates'
import { teamLogic } from '../teamLogic'
import {
    IconArrowDropDown,
    InsightsFunnelsIcon,
    InsightsLifecycleIcon,
    InsightsPathsIcon,
    InsightsRetentionIcon,
    InsightsSessionsIcon,
    InsightsStickinessIcon,
    InsightsTrendsIcon,
} from 'lib/components/icons'
import { SceneExport } from 'scenes/sceneTypes'
import { TZLabel } from 'lib/components/TimezoneAware'
import { urls } from 'scenes/urls'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { dayjs } from 'lib/dayjs'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { LemonSpacer } from 'lib/components/LemonRow'
import { More } from 'lib/components/LemonButton/More'
import { createdAtColumn, createdByColumn } from 'lib/components/LemonTable/columnUtils'
import { LemonButton } from 'lib/components/LemonButton'

const { TabPane } = Tabs

interface InsightTypeMetadata {
    name: string
    description?: string
    icon?: (props?: any) => JSX.Element
    inMenu: boolean
}

export const INSIGHT_TYPES_METADATA: Record<InsightType, InsightTypeMetadata> = {
    [InsightType.TRENDS]: {
        name: 'Trends',
        description: 'Visualize and break down how actions or events vary over time',
        icon: InsightsTrendsIcon,
        inMenu: true,
    },
    [InsightType.FUNNELS]: {
        name: 'Funnels',
        description: 'Discover how many users complete or drop out of a sequence of actions',
        icon: InsightsFunnelsIcon,
        inMenu: true,
    },
    [InsightType.SESSIONS]: {
        name: 'Sessions',
        description: 'View the average and distribution of session durations',
        icon: InsightsSessionsIcon,
        inMenu: false,
    },
    [InsightType.RETENTION]: {
        name: 'Retention',
        description: 'See how many users return on subsequent days after an intial action',
        icon: InsightsRetentionIcon,
        inMenu: true,
    },
    [InsightType.PATHS]: {
        name: 'Paths',
        description: 'Trace the journeys users take within your product and where they drop off',
        icon: InsightsPathsIcon,
        inMenu: true,
    },
    [InsightType.STICKINESS]: {
        name: 'Stickiness',
        description: 'See what keeps users coming back by viewing the interval between repeated actions',
        icon: InsightsStickinessIcon,
        inMenu: true,
    },
    [InsightType.LIFECYCLE]: {
        name: 'Lifecycle',
        description: 'Understand growth by breaking down new, resurrected, returning and dormant users',
        icon: InsightsLifecycleIcon,
        inMenu: true,
    },
}

export const scene: SceneExport = {
    component: SavedInsights,
    logic: savedInsightsLogic,
}

function NewInsightButton(): JSX.Element {
    const menu = (
        <Menu
            style={{
                maxWidth: '19rem',
                borderRadius: 'var(--radius)',
                border: '1px solid var(--primary)',
                padding: '0.5rem',
            }}
        >
            {Object.entries(INSIGHT_TYPES_METADATA).map(
                ([listedInsightType, listedInsightTypeMetadata]) =>
                    listedInsightTypeMetadata.inMenu && (
                        <Menu.Item
                            key={listedInsightType}
                            onClick={() => {
                                eventUsageLogic.actions.reportSavedInsightNewInsightClicked(listedInsightType)
                                router.actions.push(urls.insightNew({ insight: listedInsightType as InsightType }))
                            }}
                            data-attr="saved-insights-create-new-insight"
                            data-attr-insight-type={listedInsightType}
                        >
                            <Row wrap={false}>
                                <Col flex="none">
                                    {listedInsightTypeMetadata.icon && (
                                        <div style={{ fontSize: '2rem' }}>
                                            <listedInsightTypeMetadata.icon color="var(--muted-alt)" noBackground />
                                        </div>
                                    )}
                                </Col>
                                <Col flex="Auto" style={{ paddingLeft: '1rem' }}>
                                    <strong>{listedInsightTypeMetadata.name}</strong>
                                    <br />
                                    <div style={{ whiteSpace: 'initial', fontSize: '0.8125rem' }}>
                                        {listedInsightTypeMetadata.description}
                                    </div>
                                </Col>
                            </Row>
                        </Menu.Item>
                    )
            )}
        </Menu>
    )

    return (
        <Dropdown.Button
            overlayStyle={{ borderColor: 'var(--primary)' }}
            style={{ marginLeft: 8 }}
            type="primary"
            onClick={() => {
                router.actions.push(urls.insightNew({ insight: InsightType.TRENDS }))
            }}
            overlay={menu}
            icon={<IconArrowDropDown style={{ fontSize: 25 }} data-attr="saved-insights-new-insight-dropdown" />}
        >
            <PlusOutlined />
            New Insight
        </Dropdown.Button>
    )
}

export function SavedInsights(): JSX.Element {
    const { loadInsights, updateFavoritedInsight, renameInsight, duplicateInsight, setSavedInsightsFilters } =
        useActions(savedInsightsLogic)
    const { insights, count, insightsLoading, filters, sorting } = useValues(savedInsightsLogic)

    const { hasDashboardCollaboration } = useValues(organizationLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { members } = useValues(membersLogic)

    const { tab, createdBy, layoutView, search, insightType, dateFrom, dateTo, page } = filters

    const startCount = (page - 1) * INSIGHTS_PER_PAGE + 1
    const endCount = page * INSIGHTS_PER_PAGE < count ? page * INSIGHTS_PER_PAGE : count

    const columns: LemonTableColumns<DashboardItemType> = [
        {
            key: 'id',
            className: 'icon-column',
            width: 0,
            render: function renderType(_, insight) {
                const typeMetadata = INSIGHT_TYPES_METADATA[insight.filters?.insight || InsightType.TRENDS]
                if (typeMetadata && typeMetadata.icon) {
                    return (
                        <span style={{ fontSize: '2rem' }}>
                            <typeMetadata.icon />
                        </span>
                    )
                }
            },
        },
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function renderName(name: string, insight) {
                return (
                    <Col>
                        <Row wrap={false}>
                            <Link to={urls.insightView(insight.short_id, insight.filters)}>
                                <h4 className="row-name">{name || <i>{UNNAMED_INSIGHT_NAME}</i>}</h4>
                            </Link>
                            <div
                                style={{ cursor: 'pointer', width: 'fit-content', marginLeft: 8 }}
                                onClick={() => updateFavoritedInsight(insight, !insight.favorited)}
                            >
                                {insight.favorited ? (
                                    <StarFilled className="text-warning" />
                                ) : (
                                    <StarOutlined className="star-outlined" />
                                )}
                            </div>
                        </Row>
                        {hasDashboardCollaboration && insight.description && (
                            <span className="row-description">{insight.description}</span>
                        )}
                    </Col>
                )
            },
        },
        ...(hasDashboardCollaboration
            ? [
                  {
                      title: 'Tags',
                      dataIndex: 'tags' as keyof DashboardItemType,
                      key: 'tags',
                      render: function renderTags(tags: string[]) {
                          return <ObjectTags tags={tags} staticOnly />
                      },
                  },
              ]
            : []),
        ...(tab === SavedInsightsTabs.Yours
            ? []
            : [createdByColumn() as LemonTableColumn<DashboardItemType, keyof DashboardItemType | undefined>]),
        createdAtColumn() as LemonTableColumn<DashboardItemType, keyof DashboardItemType | undefined>,
        {
            title: 'Last modified',
            sorter: true,
            dataIndex: 'updated_at',
            render: function renderLastModified(updated_at: string) {
                return <div style={{ whiteSpace: 'nowrap' }}>{updated_at && <TZLabel time={updated_at} />}</div>
            },
        },
        {
            width: 0,
            render: function Render(_, insight) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    type="stealth"
                                    to={urls.insightView(insight.short_id, insight.filters)}
                                    fullWidth
                                >
                                    View
                                </LemonButton>
                                <LemonButton
                                    type="stealth"
                                    onClick={() => renameInsight(insight)}
                                    data-attr={`insight-item-${insight.short_id}-dropdown-rename`}
                                    fullWidth
                                >
                                    Rename
                                </LemonButton>
                                <LemonButton
                                    type="stealth"
                                    onClick={() => duplicateInsight(insight)}
                                    data-attr={`insight-item-${insight.short_id}-dropdown-duplicate`}
                                    fullWidth
                                >
                                    Duplicate
                                </LemonButton>
                                <LemonSpacer />
                                <LemonButton
                                    type="stealth"
                                    style={{ color: 'var(--danger)' }}
                                    onClick={() =>
                                        deleteWithUndo({
                                            object: insight,
                                            endpoint: `projects/${currentTeamId}/insights`,
                                            callback: loadInsights,
                                        })
                                    }
                                    data-attr={`insight-item-${insight.short_id}-dropdown-remove`}
                                    fullWidth
                                >
                                    Delete insight
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="saved-insights">
            <PageHeader title="Insights" buttons={<NewInsightButton />} />

            <Tabs
                activeKey={tab}
                style={{ borderColor: '#D9D9D9' }}
                onChange={(t) => setSavedInsightsFilters({ tab: t as SavedInsightsTabs })}
            >
                <TabPane tab="All Insights" key={SavedInsightsTabs.All} />
                <TabPane tab="Your Insights" key={SavedInsightsTabs.Yours} />
                <TabPane tab="Favorites" key={SavedInsightsTabs.Favorites} />
            </Tabs>
            <Row style={{ paddingBottom: 16, justifyContent: 'space-between', gap: '0.75rem' }}>
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
                <Row style={{ gap: '0.75rem' }}>
                    <Col>
                        Type:
                        <Select
                            className="insight-type-icon-dropdown"
                            value={insightType}
                            style={{ paddingLeft: 8, width: 140 }}
                            onChange={(it) => setSavedInsightsFilters({ insightType: it })}
                        >
                            {Object.entries({
                                ['All types']: {
                                    name: 'All types',
                                    inMenu: false,
                                } as InsightTypeMetadata,
                                ...INSIGHT_TYPES_METADATA,
                            }).map(([listedInsightType, listedInsightTypeMetadata], index) => (
                                <Select.Option key={index} value={listedInsightType}>
                                    <div className="insight-type-icon-wrapper">
                                        {listedInsightTypeMetadata.icon ? (
                                            <div className="icon-container">
                                                <div className="icon-container-inner">
                                                    {<listedInsightTypeMetadata.icon color="#747EA2" noBackground />}
                                                </div>
                                            </div>
                                        ) : null}
                                        <div>{listedInsightTypeMetadata.name}</div>
                                    </div>
                                </Select.Option>
                            ))}
                        </Select>
                    </Col>
                    <Col>
                        Last modified:
                        <DateFilter
                            style={{ paddingLeft: 8 }}
                            defaultValue="All time"
                            disabled={false}
                            bordered={true}
                            dateFrom={dateFrom}
                            dateTo={dateTo}
                            onChange={(fromDate, toDate) =>
                                setSavedInsightsFilters({ dateFrom: fromDate, dateTo: toDate })
                            }
                        />
                    </Col>
                    {tab !== SavedInsightsTabs.Yours ? (
                        <Col>
                            Created by:
                            <Select
                                value={createdBy}
                                style={{ paddingLeft: 8, width: 140 }}
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
                    ) : null}
                </Row>
            </Row>
            <Row className="list-or-card-layout">
                {count
                    ? `${startCount}${endCount - startCount > 1 ? '-' + endCount : ''} of ${count} insight${
                          count === 1 ? '' : 's'
                      }`
                    : 'No insights yet'}
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
            {!insightsLoading && insights.count < 1 ? (
                <SavedInsightsEmptyState />
            ) : (
                <>
                    {layoutView === LayoutView.List ? (
                        <LemonTable
                            loading={insightsLoading}
                            columns={columns}
                            dataSource={insights.results}
                            pagination={{
                                controlled: true,
                                pageSize: INSIGHTS_PER_PAGE,
                                currentPage: page,
                                entryCount: count,
                                onBackward: () =>
                                    setSavedInsightsFilters({
                                        page: page - 1,
                                    }),
                                onForward: () =>
                                    setSavedInsightsFilters({
                                        page: page + 1,
                                    }),
                            }}
                            disableSortingCancellation
                            sorting={sorting}
                            onSort={(newSorting) =>
                                setSavedInsightsFilters({
                                    order: newSorting
                                        ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                        : undefined,
                                })
                            }
                            rowKey="id"
                            nouns={['insight', 'insights']}
                        />
                    ) : (
                        <Row gutter={[16, 16]}>
                            {insights &&
                                insights.results.map((insight: DashboardItemType, index: number) => (
                                    <Col
                                        xs={24}
                                        sm={24}
                                        md={24}
                                        lg={12}
                                        xl={12}
                                        xxl={8}
                                        key={insight.short_id}
                                        style={{ height: 340 }}
                                    >
                                        <DashboardItem
                                            item={{ ...insight, color: null }}
                                            key={insight.short_id + '_user'}
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
