import './SavedInsights.scss'

import { useActions, useValues } from 'kea'

import { IconMinusSmall, IconPlusSmall } from '@posthog/icons'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { SavedInsightsEmptyState } from 'scenes/insights/EmptyStates'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { organizationLogic } from 'scenes/organizationLogic'
import { SavedInsightsFilters } from 'scenes/saved-insights/SavedInsightsFilters'
import { urls } from 'scenes/urls'

import { QueryBasedInsightModel, SavedInsightsTabs } from '~/types'

import { InsightIcon } from './SavedInsights'
import { INSIGHTS_PER_PAGE, addSavedInsightsModalLogic } from './addSavedInsightsModalLogic'

export function AddSavedInsightsToDashboard(): JSX.Element {
    const { modalPage, insights, count, insightsLoading, filters, sorting, dashboardUpdatesInProgress } =
        useValues(addSavedInsightsModalLogic)
    const { setModalPage, addInsightToDashboard, removeInsightFromDashboard, setModalFilters } =
        useActions(addSavedInsightsModalLogic)

    const { hasTagging } = useValues(organizationLogic)
    const { dashboard } = useValues(dashboardLogic)

    const summarizeInsight = useSummarizeInsight()

    const { tab } = filters

    const startCount = (modalPage - 1) * INSIGHTS_PER_PAGE + 1
    const endCount = Math.min(modalPage * INSIGHTS_PER_PAGE, count)

    const columns: LemonTableColumns<QueryBasedInsightModel> = [
        {
            width: 0,
            render: function Render(_, insight) {
                const isInDashboard = dashboard?.tiles.some((tile) => tile.insight?.id === insight.id)
                return (
                    <LemonButton
                        type="secondary"
                        status={isInDashboard ? 'danger' : 'default'}
                        size="small"
                        fullWidth
                        disabled={dashboardUpdatesInProgress[insight.id]}
                        onClick={(e) => {
                            e.preventDefault()
                            if (dashboardUpdatesInProgress[insight.id]) {
                                return
                            }
                            isInDashboard
                                ? removeInsightFromDashboard(insight, dashboard?.id || 0)
                                : addInsightToDashboard(insight, dashboard?.id || 0)
                        }}
                    >
                        {dashboardUpdatesInProgress[insight.id] ? (
                            <Spinner textColored />
                        ) : isInDashboard ? (
                            <IconMinusSmall />
                        ) : (
                            <IconPlusSmall />
                        )}
                    </LemonButton>
                )
            },
        },
        {
            key: 'id',
            width: 32,
            render: function renderType(_, insight) {
                return <InsightIcon insight={insight} className="text-secondary text-2xl" />
            },
        },
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function renderName(name: string, insight) {
                return (
                    <>
                        <div className="flex flex-col gap-1 min-w-0">
                            <div className="flex min-w-0">
                                <Link
                                    to={urls.insightView(insight.short_id)}
                                    target="_blank"
                                    title={name || summarizeInsight(insight.query)}
                                    className="w-0 flex-1 min-w-0"
                                >
                                    <span className="block truncate">
                                        {name || <i>{summarizeInsight(insight.query)}</i>}
                                    </span>
                                </Link>
                            </div>
                            <div className="text-xs text-tertiary">{insight.description}</div>
                        </div>
                    </>
                )
            },
        },
        ...(hasTagging
            ? [
                  {
                      title: 'Tags',
                      dataIndex: 'tags' as keyof QueryBasedInsightModel,
                      key: 'tags',
                      render: function renderTags(tags: string[]) {
                          return <ObjectTags tags={tags} staticOnly />
                      },
                  },
              ]
            : []),
        ...(tab === SavedInsightsTabs.Yours
            ? []
            : [
                  createdByColumn() as LemonTableColumn<
                      QueryBasedInsightModel,
                      keyof QueryBasedInsightModel | undefined
                  >,
              ]),
        createdAtColumn() as LemonTableColumn<QueryBasedInsightModel, keyof QueryBasedInsightModel | undefined>,
        {
            title: 'Last modified',
            sorter: true,
            dataIndex: 'last_modified_at',
            render: function renderLastModified(last_modified_at: string) {
                return (
                    <div className="whitespace-nowrap">{last_modified_at && <TZLabel time={last_modified_at} />}</div>
                )
            },
        },
    ]

    return (
        <div className="saved-insights">
            <SavedInsightsFilters filters={filters} setFilters={setModalFilters} />
            <LemonDivider className="my-4" />
            <div className="flex justify-between mb-4 gap-2 flex-wrap mt-2 items-center">
                <span className="text-secondary">
                    {count
                        ? `${startCount}${endCount - startCount > 1 ? '-' + endCount : ''} of ${count} insight${
                              count === 1 ? '' : 's'
                          }`
                        : null}
                </span>
            </div>
            {!insightsLoading && insights.count < 1 ? (
                <SavedInsightsEmptyState filters={filters} usingFilters />
            ) : (
                <>
                    <LemonTable
                        loading={insightsLoading}
                        columns={columns}
                        dataSource={insights.results}
                        pagination={{
                            controlled: true,
                            currentPage: modalPage,
                            pageSize: INSIGHTS_PER_PAGE,
                            entryCount: count,
                            onForward: () => setModalPage(modalPage + 1),
                            onBackward: () => setModalPage(modalPage - 1),
                        }}
                        sorting={sorting}
                        onSort={(newSorting) =>
                            setModalFilters({
                                order: newSorting
                                    ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                    : undefined,
                            })
                        }
                        rowKey="id"
                        loadingSkeletonRows={INSIGHTS_PER_PAGE}
                        nouns={['insight', 'insights']}
                    />
                </>
            )}
        </div>
    )
}
