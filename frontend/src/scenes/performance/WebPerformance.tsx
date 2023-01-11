import './WebPerformance.scss'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { PageHeader } from 'lib/components/PageHeader'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator, RecentPerformancePageView } from '~/types'
import { webPerformanceLogic, WebPerformancePage } from 'scenes/performance/webPerformanceLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { useValues } from 'kea'
import { WebPerformanceWaterfallChart } from 'scenes/performance/WebPerformanceWaterfallChart'
import { IconPlay } from 'lib/components/icons'
import { LemonButton, LemonTable, Link } from '@posthog/lemon-ui'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Query } from '~/queries/Query/Query'
import { NodeKind, RecentPerformancePageViewNode } from '~/queries/schema'
import { humanFriendlyDuration } from 'lib/utils'
import { LemonTableColumn } from 'lib/components/LemonTable'
import { TZLabel } from 'lib/components/TZLabel'

/*
 * link to SessionRecording from table and chart
 * show histogram of pageload instead of table
 */

export const webPerformancePropertyFilters: AnyPropertyFilter[] = [
    {
        key: '$performance_raw',
        value: 'is_set',
        operator: PropertyOperator.IsSet,
        type: PropertyFilterType.Event,
    },
]

function WaterfallButton(props: { record: RecentPerformancePageView; onClick: () => void }): JSX.Element {
    return (
        <div>
            <LemonButton
                data-attr={`view-waterfall-button-${props.record.pageview_id}`}
                icon={<IconPlay />}
                type="secondary"
                size="small"
                to={urls.webPerformanceWaterfall(props.record)}
            >
                View waterfall chart
            </LemonButton>
        </div>
    )
}

const EventsWithPerformanceTable = (): JSX.Element => {
    const { recentPageViews, recentPageViewsLoading } = useValues(webPerformanceLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const featureDataExploration = featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_LIVE_EVENTS]

    const oldFashionedColumns: LemonTableColumn<
        RecentPerformancePageView,
        keyof RecentPerformancePageView | undefined
    >[] = [
        {
            title: 'Page',
            key: 'page_url',
            width: '45%',
            render: function render(_, item: RecentPerformancePageView) {
                return <div className={'max-w-100 overflow-auto'}>{item.page_url}</div>
            },
        },
        {
            title: 'Page load',
            key: 'duration',
            render: function render(_, item: RecentPerformancePageView) {
                return item.duration ? <>{humanFriendlyDuration(item.duration / 1000)}</> : <>-</>
            },
        },
        {
            title: 'timestamp',
            key: 'timestamp',
            render: function render(_, item: RecentPerformancePageView) {
                return <TZLabel time={item.timestamp} />
            },
        },
        {
            title: '',
            render: function render(_, item: RecentPerformancePageView) {
                return <WaterfallButton record={item} onClick={() => console.log(item)} />
            },
        },
    ]

    return (
        <>
            <div className="pt-4 border-t" />
            {featureDataExploration ? (
                <Query
                    query={{
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.RecentPerformancePageViewNode,
                        },
                        columns: [
                            'context.columns.page_url',
                            'context.columns.duration',
                            'timestamp',
                            'context.columns.waterfallButton',
                        ],
                        showReload: true,
                        showColumnConfigurator: false,
                        showExport: false,
                        showEventFilter: false,
                        showPropertyFilter: false,
                        showActions: false,
                        expandable: false,
                    }}
                    context={{
                        columns: {
                            page_url: {
                                title: 'Page',
                                render: function RenderPageURL({
                                    record,
                                }: {
                                    record: Required<RecentPerformancePageViewNode>['response']['results'][0]
                                }) {
                                    return record.page_url ? (
                                        <div className={'max-w-100 overflow-auto'}>{record.page_url}</div>
                                    ) : (
                                        <>-</>
                                    )
                                },
                            },
                            duration: {
                                title: 'Page load',
                                render: function RenderPageLoad({
                                    record,
                                }: {
                                    record: Required<RecentPerformancePageViewNode>['response']['results'][0]
                                }) {
                                    return record.duration ? (
                                        <>{humanFriendlyDuration(record.duration / 1000)}</>
                                    ) : (
                                        <>-</>
                                    )
                                },
                            },
                            waterfallButton: {
                                title: '',
                                render: function RenderWaterfallButton({
                                    record,
                                }: {
                                    record: Required<RecentPerformancePageViewNode>['response']['results'][0]
                                }) {
                                    return <WaterfallButton record={record} onClick={() => console.log(record)} />
                                },
                            },
                        },
                    }}
                />
            ) : (
                <LemonTable
                    data-attr="web-performance-table"
                    dataSource={recentPageViews}
                    loading={recentPageViewsLoading}
                    columns={oldFashionedColumns}
                    loadingSkeletonRows={20}
                    emptyState={recentPageViewsLoading ? undefined : <>need an empty state that makes sense</>}
                    rowKey={(row) => row.pageview_id}
                />
            )}
        </>
    )
}

export const WebPerformance = (): JSX.Element => {
    const { currentPage } = useValues(webPerformanceLogic)

    return (
        <div className="web-performance">
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Web Performance
                        <LemonTag type="warning" className="uppercase">
                            Alpha
                        </LemonTag>
                    </div>
                }
                caption={
                    currentPage === WebPerformancePage.TABLE ? (
                        <div>
                            <p>
                                Shows page view events where performance information has been captured. Not all events
                                have all performance information.
                            </p>
                            <p>
                                To capture performance information you must be using posthog-js and set{' '}
                                <code>_capture_performance</code> to true. See the{' '}
                                <Link
                                    to="https://posthog.com/docs/integrate/client/js#config"
                                    disableClientSideRouting={true}
                                >
                                    config instructions in our handbook
                                </Link>
                            </p>
                        </div>
                    ) : null
                }
            />
            <div>
                {currentPage === WebPerformancePage.TABLE ? (
                    <EventsWithPerformanceTable />
                ) : currentPage === WebPerformancePage.WATERFALL_CHART ? (
                    <WebPerformanceWaterfallChart />
                ) : (
                    <>404?</>
                )}
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: WebPerformance,
    logic: webPerformanceLogic,
    paramsToProps: () => ({ sceneUrl: urls.webPerformance() }),
}
