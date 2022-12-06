import './WebPerformance.scss'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { PageHeader } from 'lib/components/PageHeader'
import { AnyPropertyFilter, EventsTableRowItem, PropertyFilterType, PropertyOperator } from '~/types'
import { webPerformanceLogic, WebPerformancePage } from 'scenes/performance/webPerformanceLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { EventsTable } from 'scenes/events'
import { useActions, useValues } from 'kea'
import { WebPerformanceWaterfallChart } from 'scenes/performance/WebPerformanceWaterfallChart'
import { IconPlay } from 'lib/components/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Query } from '~/queries/Query/Query'
import { EventsNode, NodeKind } from '~/queries/schema'

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

const EventsWithPerformanceTable = (): JSX.Element => {
    const { setEventToDisplay } = useActions(webPerformanceLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const featureDataExploration = featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_LIVE_EVENTS]

    return (
        <>
            <div className="pt-4 border-t" />
            {featureDataExploration ? (
                <Query
                    query={{
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.EventsNode,
                            fixedProperties: webPerformancePropertyFilters,
                        },
                        columns: [
                            'properties.$current_url',
                            'properties.$lib',
                            'timestamp',
                            'context.columns.waterfallButton',
                        ],
                        showReload: true,
                        showColumnConfigurator: false,
                        showExport: true,
                        showEventFilter: false,
                        showPropertyFilter: true,
                        showActions: false,
                        expandable: false,
                    }}
                    context={{
                        columns: {
                            waterfallButton: {
                                title: '',
                                render: function RenderWaterfallButton({
                                    record: event,
                                }: {
                                    record: Required<EventsNode>['response']['results'][0]
                                }) {
                                    return (
                                        <div>
                                            <LemonButton
                                                data-attr={`view-waterfall-button-${event?.id}`}
                                                icon={<IconPlay />}
                                                type="secondary"
                                                size="small"
                                                onClick={() => setEventToDisplay(event)}
                                            >
                                                View waterfall chart
                                            </LemonButton>
                                        </div>
                                    )
                                },
                            },
                        },
                    }}
                />
            ) : (
                <EventsTable
                    fixedFilters={{
                        properties: webPerformancePropertyFilters,
                    }}
                    sceneUrl={urls.webPerformance()}
                    fetchMonths={1}
                    pageKey={`webperformance-${JSON.stringify(webPerformancePropertyFilters)}`}
                    showPersonColumn={false}
                    showCustomizeColumns={false}
                    showExport={false}
                    showAutoload={false}
                    showEventFilter={false}
                    showPropertyFilter={true}
                    showRowExpanders={false}
                    showActionsButton={false}
                    linkPropertiesToFilters={false}
                    data-attr="waterfall-events-table"
                    startingColumns={['$current_url', '$performance_page_loaded']}
                    fixedColumns={[
                        {
                            render: function RenderViewButton(_: any, { event }: EventsTableRowItem) {
                                if (!event) {
                                    return { props: { colSpan: 0 } }
                                }
                                return (
                                    <div>
                                        <LemonButton
                                            data-attr={`view-waterfall-button-${event?.id}`}
                                            icon={<IconPlay />}
                                            type="secondary"
                                            size="small"
                                            onClick={() => {
                                                setEventToDisplay(event)
                                            }}
                                        >
                                            View waterfall chart
                                        </LemonButton>
                                    </div>
                                )
                            },
                        },
                    ]}
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
                                <a href="https://posthog.com/docs/integrate/client/js#config" target="_blank">
                                    config instructions in our handbook
                                </a>
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
