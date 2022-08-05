import { Col, Input, Radio, Row, Select, Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { deleteWithUndo, Loading } from 'lib/utils'
import React from 'react'
import { InsightModel, InsightType, LayoutView, SavedInsightsTabs } from '~/types'
import { INSIGHTS_PER_PAGE, savedInsightsLogic } from './savedInsightsLogic'
import { AppstoreFilled, StarFilled, StarOutlined, UnorderedListOutlined } from '@ant-design/icons'
import './SavedInsights.scss'
import { organizationLogic } from 'scenes/organizationLogic'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PageHeader } from 'lib/components/PageHeader'
import { SavedInsightsEmptyState } from 'scenes/insights/EmptyStates'
import { teamLogic } from '../teamLogic'
import {
    InsightsFunnelsIcon,
    InsightsLifecycleIcon,
    InsightsPathsIcon,
    InsightsRetentionIcon,
    InsightsStickinessIcon,
    InsightsTrendsIcon,
} from 'lib/components/icons'
import { SceneExport } from 'scenes/sceneTypes'
import { TZLabel } from 'lib/components/TimezoneAware'
import { urls } from 'scenes/urls'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { LemonDivider } from 'lib/components/LemonDivider'
import { More } from 'lib/components/LemonButton/More'
import { createdAtColumn, createdByColumn } from 'lib/components/LemonTable/columnUtils'
import { LemonButton, LemonButtonWithSideAction } from 'lib/components/LemonButton'
import { InsightCard } from 'lib/components/InsightCard'
import { summarizeInsightFilters } from 'scenes/insights/utils'
import { groupsModel } from '~/models/groupsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { PaginationControl, usePagination } from 'lib/components/PaginationControl'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { insightActivityDescriber } from 'scenes/saved-insights/activityDescriptions'
import { CalendarOutlined } from '@ant-design/icons'

const { TabPane } = Tabs

export interface InsightTypeMetadata {
    name: string
    description?: string
    icon: (props?: any) => JSX.Element
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
        name: 'Funnel',
        description: 'Discover how many users complete or drop out of a sequence of actions',
        icon: InsightsFunnelsIcon,
        inMenu: true,
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

export function InsightIcon({ insight }: { insight: InsightModel }): JSX.Element | null {
    const insightMetadata = INSIGHT_TYPES_METADATA[insight?.filters?.insight || InsightType.TRENDS]
    if (insightMetadata && insightMetadata.icon) {
        return <insightMetadata.icon style={{ display: 'block', fontSize: '2rem' }} />
    }
    return null
}

function NewInsightButton(): JSX.Element {
    return (
        <LemonButtonWithSideAction
            type="primary"
            to={urls.insightNew()}
            sideAction={{
                popup: {
                    placement: 'bottom-end',
                    className: 'new-insight-overlay',
                    actionable: true,
                    overlay: Object.entries(INSIGHT_TYPES_METADATA).map(
                        ([listedInsightType, listedInsightTypeMetadata]) =>
                            listedInsightTypeMetadata.inMenu && (
                                <LemonButton
                                    key={listedInsightType}
                                    type="stealth"
                                    icon={
                                        listedInsightTypeMetadata.icon && (
                                            <listedInsightTypeMetadata.icon color="var(--muted-alt)" noBackground />
                                        )
                                    }
                                    to={urls.insightNew({ insight: listedInsightType as InsightType })}
                                    data-attr="saved-insights-create-new-insight"
                                    data-attr-insight-type={listedInsightType}
                                    onClick={() => {
                                        eventUsageLogic.actions.reportSavedInsightNewInsightClicked(listedInsightType)
                                    }}
                                    fullWidth
                                    extendedContent={listedInsightTypeMetadata.description}
                                >
                                    <strong>{listedInsightTypeMetadata.name}</strong>
                                </LemonButton>
                            )
                    ),
                },
                'data-attr': 'saved-insights-new-insight-dropdown',
            }}
            data-attr="saved-insights-new-insight-button"
        >
            New insight
        </LemonButtonWithSideAction>
    )
}

function SavedInsightsGrid(): JSX.Element {
    const { loadInsights, renameInsight, duplicateInsight } = useActions(savedInsightsLogic)
    const { insights, insightsLoading, pagination } = useValues(savedInsightsLogic)
    const { currentTeamId } = useValues(teamLogic)

    const paginationState = usePagination(insights?.results || [], pagination)

    return (
        <>
            <div className="saved-insights-grid">
                {paginationState.dataSourcePage.map((insight: InsightModel) => (
                    <InsightCard
                        key={insight.short_id}
                        insight={{ ...insight, color: null }}
                        rename={() => renameInsight(insight)}
                        duplicate={() => duplicateInsight(insight)}
                        deleteWithUndo={() =>
                            deleteWithUndo({
                                object: insight,
                                endpoint: `projects/${currentTeamId}/insights`,
                                callback: loadInsights,
                            })
                        }
                    />
                ))}
                {insightsLoading && <Loading />}
            </div>
            <PaginationControl {...paginationState} nouns={['insight', 'insights']} />
        </>
    )
}

export function SavedInsights(): JSX.Element {
    const { loadInsights, updateFavoritedInsight, renameInsight, duplicateInsight, setSavedInsightsFilters } =
        useActions(savedInsightsLogic)
    const { insights, count, insightsLoading, filters, sorting, pagination } = useValues(savedInsightsLogic)
    const { hasDashboardCollaboration } = useValues(organizationLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { meFirstMembers } = useValues(membersLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { cohortsById } = useValues(cohortsModel)
    const { mathDefinitions } = useValues(mathsLogic)

    const { tab, createdBy, layoutView, search, insightType, dateFrom, dateTo, page } = filters

    const startCount = (page - 1) * INSIGHTS_PER_PAGE + 1
    const endCount = page * INSIGHTS_PER_PAGE < count ? page * INSIGHTS_PER_PAGE : count

    const columns: LemonTableColumns<InsightModel> = [
        {
            key: 'id',
            className: 'icon-column',
            width: 32,
            render: function renderType(_, insight) {
                return <InsightIcon insight={insight} />
            },
        },
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function renderName(name: string, insight) {
                return (
                    <>
                        <div style={{ display: 'flex', alignItems: 'center' }}>
                            <Link to={urls.insightView(insight.short_id)} className="row-name">
                                {name || (
                                    <i>
                                        {summarizeInsightFilters(
                                            insight.filters,
                                            aggregationLabel,
                                            cohortsById,
                                            mathDefinitions
                                        )}
                                    </i>
                                )}
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
                        </div>
                        {hasDashboardCollaboration && insight.description && (
                            <span className="row-description">{insight.description}</span>
                        )}
                    </>
                )
            },
        },
        ...(hasDashboardCollaboration
            ? [
                  {
                      title: 'Tags',
                      dataIndex: 'tags' as keyof InsightModel,
                      key: 'tags',
                      render: function renderTags(tags: string[]) {
                          return <ObjectTags tags={tags} staticOnly />
                      },
                  },
              ]
            : []),
        ...(tab === SavedInsightsTabs.Yours
            ? []
            : [createdByColumn() as LemonTableColumn<InsightModel, keyof InsightModel | undefined>]),
        createdAtColumn() as LemonTableColumn<InsightModel, keyof InsightModel | undefined>,
        {
            title: 'Last modified',
            sorter: true,
            dataIndex: 'last_modified_at',
            render: function renderLastModified(last_modified_at: string) {
                return (
                    <div style={{ whiteSpace: 'nowrap' }}>
                        {last_modified_at && <TZLabel time={last_modified_at} />}
                    </div>
                )
            },
        },
        {
            width: 0,
            render: function Render(_, insight) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton type="stealth" to={urls.insightView(insight.short_id)} fullWidth>
                                    View
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton type="stealth" to={urls.insightEdit(insight.short_id)} fullWidth>
                                    Edit
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
                                <LemonDivider />
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
                <TabPane tab="History" key={SavedInsightsTabs.History} />
            </Tabs>

            {tab === SavedInsightsTabs.History ? (
                <ActivityLog scope={ActivityScope.INSIGHT} describer={insightActivityDescriber} />
            ) : (
                <>
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
                                                            {
                                                                <listedInsightTypeMetadata.icon
                                                                    color="#747EA2"
                                                                    noBackground
                                                                />
                                                            }
                                                        </div>
                                                    </div>
                                                ) : null}
                                                <div>{listedInsightTypeMetadata.name}</div>
                                            </div>
                                        </Select.Option>
                                    ))}
                                </Select>
                            </Col>
                            <div className="flex items-center gap-2">
                                <span>Last modified:</span>
                                <DateFilter
                                    defaultValue="All time"
                                    disabled={false}
                                    dateFrom={dateFrom}
                                    dateTo={dateTo}
                                    onChange={(fromDate, toDate) =>
                                        setSavedInsightsFilters({ dateFrom: fromDate, dateTo: toDate })
                                    }
                                    makeLabel={(key) => (
                                        <>
                                            <CalendarOutlined />
                                            <span className="hide-when-small"> {key}</span>
                                        </>
                                    )}
                                />
                            </div>
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
                                        {meFirstMembers.map((member) => (
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
                                    <UnorderedListOutlined className="mr-2" />
                                    List
                                </Radio.Button>
                                <Radio.Button value={LayoutView.Card}>
                                    <AppstoreFilled className="mr-2" />
                                    Cards
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
                                    pagination={pagination}
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
                                    loadingSkeletonRows={15}
                                    nouns={['insight', 'insights']}
                                />
                            ) : (
                                <SavedInsightsGrid />
                            )}
                        </>
                    )}
                </>
            )}
        </div>
    )
}
