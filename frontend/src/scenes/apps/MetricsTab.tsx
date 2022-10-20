import { AppErrorSummary, AppMetrics, appMetricsSceneLogic, AppMetricsTab } from './appMetricsSceneLogic'
import { DescriptionColumns } from './constants'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { humanFriendlyNumber } from 'lib/utils'
import { AppMetricsGraph } from './AppMetricsGraph'
import { LemonSelect } from 'lib/components/LemonSelect'
import { useActions, useValues } from 'kea'
import { LemonTable } from '../../lib/components/LemonTable'
import { TZLabel } from 'lib/components/TimezoneAware'
import { Link } from '../../lib/components/Link'
import clsx from 'clsx'

export interface MetricsTabProps {
    tab: AppMetricsTab
}

export interface MetricsOverviewProps {
    tab: AppMetricsTab
    metrics?: AppMetrics | null
    metricsLoading: boolean
}

export function MetricsTab({ tab }: MetricsTabProps): JSX.Element {
    const { appMetricsResponse, appMetricsResponseLoading, dateFrom } = useValues(appMetricsSceneLogic)
    const { setDateFrom } = useActions(appMetricsSceneLogic)

    return (
        <div className="space-y-8">
            <div>
                {/* <h2>Overview</h2> */}

                <div className="flex items-start justify-between gap-2">
                    <MetricsOverview
                        tab={tab}
                        metrics={appMetricsResponse?.metrics}
                        metricsLoading={appMetricsResponseLoading}
                    />

                    <LemonSelect
                        value={dateFrom}
                        onChange={(newValue) => setDateFrom(newValue as string)}
                        options={[
                            { label: 'Last 30 days', value: '-30d' },
                            { label: 'Last 7 days', value: '-7d' },
                            { label: 'Last 24 hours', value: '-24h' },
                        ]}
                    />
                </div>
            </div>

            <div>
                <h2>Delivery trends</h2>
                <AppMetricsGraph
                    tab={tab}
                    metrics={appMetricsResponse?.metrics}
                    metricsLoading={appMetricsResponseLoading}
                />
            </div>

            <div>
                <h2>Errors</h2>
                <ErrorsOverview
                    category={tab}
                    errors={appMetricsResponse?.errors || []}
                    loading={appMetricsResponseLoading}
                />
            </div>
        </div>
    )
}

export function MetricsOverview({ tab, metrics, metricsLoading }: MetricsOverviewProps): JSX.Element {
    if (metricsLoading) {
        return <LemonSkeleton className="w-20 mb-2" repeat={4} />
    }

    return (
        <div className="space-y-4">
            <div className="flex items-start gap-8 flex-wrap">
                <div>
                    <div className="text-muted font-semibold mb-2">{DescriptionColumns[tab].successes}</div>
                    <div className="text-4xl ">{renderNumber(metrics?.totals?.successes)}</div>
                </div>
                {DescriptionColumns[tab].successes_on_retry && (
                    <div>
                        <div className="text-muted font-semibold mb-2">
                            {DescriptionColumns[tab].successes_on_retry}
                        </div>
                        <div className="text-4xl ">{renderNumber(metrics?.totals?.successes_on_retry)}</div>
                    </div>
                )}
                <div>
                    <div className="text-muted font-semibold mb-2">{DescriptionColumns[tab].failures}</div>
                    <div
                        className={clsx(
                            'text-4xl '
                            // Example of adding color (should be done rarely)
                            // renderNumber(metrics?.totals?.failures) && 'text-danger'
                        )}
                    >
                        {renderNumber(metrics?.totals?.failures)}
                    </div>
                </div>
            </div>

            {/* <div>
                <div className="font-semibold text-muted">Error message</div>
                <div className="">Some thing went wrong and it was terrible</div>
            </div> */}
        </div>
    )
}

export function ErrorsOverview({
    errors,
    loading,
    category,
    jobId,
}: {
    errors: Array<AppErrorSummary>
    loading?: boolean
    category: string
    jobId?: string
}): JSX.Element {
    const { openErrorDetailsDrawer } = useActions(appMetricsSceneLogic)

    return (
        <LemonTable
            dataSource={errors}
            loading={loading}
            columns={[
                {
                    title: 'Error type',
                    dataIndex: 'error_type',
                    render: function RenderErrorType(_, errorSummary) {
                        return (
                            <Link
                                title="View details"
                                className="font-semibold"
                                onClick={(event) => {
                                    event.preventDefault()
                                    openErrorDetailsDrawer(errorSummary.error_type, category, jobId)
                                }}
                            >
                                {errorSummary.error_type}
                            </Link>
                        )
                    },
                    sorter: (a, b) => a.error_type.localeCompare(b.error_type),
                },
                {
                    title: 'Count',
                    dataIndex: 'count',
                    align: 'right',
                    sorter: (a, b) => a.count - b.count,
                },
                {
                    title: 'Last seen',
                    dataIndex: 'last_seen',
                    render: function RenderCreatedAt(lastSeen) {
                        return (
                            <div className="whitespace-nowrap text-right">
                                <TZLabel time={lastSeen as string} />
                            </div>
                        )
                    },
                    align: 'right',
                    sorter: (a, b) => (new Date(a.last_seen || 0) > new Date(b.last_seen || 0) ? 1 : -1),
                },
            ]}
            defaultSorting={{ columnKey: 'last_seen', order: -1 }}
            useURLForSorting={false}
            noSortingCancellation
            emptyState={
                <div className="">
                    <b>No errors 🥳!</b>
                    <p>If errors are shown in the future </p>
                </div>
            }
        />
    )
}

function renderNumber(value: number | undefined): JSX.Element {
    return <>{value ? humanFriendlyNumber(value) : value}</>
}
