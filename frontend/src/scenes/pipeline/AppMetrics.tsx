import { useActions, useValues } from 'kea'
import { Chart, ChartDataset, ChartItem } from 'lib/Chart'
import { getColorVar } from 'lib/colors'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { IconInfo } from 'lib/lemon-ui/icons'
import { IconChevronLeft, IconChevronRight, IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber, inStorybookTestRunner, lightenDarkenColor } from 'lib/utils'
import { useState } from 'react'
import { useEffect, useRef } from 'react'

import { AppMetricErrorDetail, AppMetricsData, appMetricsLogic, AppMetricsProps } from './appMetricsLogic'

export interface MetricsOverviewProps {
    metrics?: AppMetricsData | null
    metricsLoading: boolean
}

export function AppMetrics({ pluginConfigId }: AppMetricsProps): JSX.Element {
    const logic = appMetricsLogic({ pluginConfigId })

    const { appMetricsResponse, appMetricsResponseLoading, dateFrom } = useValues(logic)
    const { setDateFrom } = useActions(logic)

    return (
        <div className="space-y-8">
            <div className="flex items-start justify-between gap-2">
                <MetricsOverview metrics={appMetricsResponse?.metrics} metricsLoading={appMetricsResponseLoading} />

                <LemonSelect
                    value={dateFrom}
                    onChange={(newValue) => setDateFrom(newValue)}
                    options={[
                        { label: 'Last 30 days', value: '-30d' },
                        { label: 'Last 7 days', value: '-7d' },
                        { label: 'Last 24 hours', value: '-24h' },
                    ]}
                />
            </div>

            <div>
                <h2>Delivery trends</h2>
                <AppMetricsGraph metrics={appMetricsResponse?.metrics} metricsLoading={appMetricsResponseLoading} />
            </div>

            <div>
                <h2>Errors</h2>
                <ErrorsOverview pluginConfigId={pluginConfigId} />
            </div>
        </div>
    )
}

function MetricsOverview({ metrics, metricsLoading }: MetricsOverviewProps): JSX.Element {
    if (metricsLoading) {
        return <LemonSkeleton className="w-20 h-4 mb-2" repeat={4} />
    }

    return (
        <div className="space-y-4">
            <div className="flex items-start gap-8 flex-wrap">
                <div>
                    <div className="text-muted font-semibold mb-2">
                        Events Processed successfully
                        <Tooltip title="Total number of events processed successfully">
                            <IconInfo />
                        </Tooltip>
                    </div>
                    <div className="text-4xl">{renderNumber(metrics?.totals?.successes)}</div>
                </div>
                <div>
                    <div className="text-muted font-semibold mb-2">
                        Events Failed
                        <Tooltip title="Total number of events that threw an error during processing">
                            <IconInfo />
                        </Tooltip>
                    </div>
                    <div className="text-4xl">{renderNumber(metrics?.totals?.failures)}</div>
                </div>
            </div>
        </div>
    )
}

function renderNumber(value: number | undefined): JSX.Element {
    return <>{value ? humanFriendlyNumber(value) : value}</>
}

interface AppMetricsGraphProps {
    metrics?: AppMetricsData | null
    metricsLoading: boolean
}

function AppMetricsGraph({ metrics, metricsLoading }: AppMetricsGraphProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)

    useEffect(() => {
        let chart: Chart
        if (canvasRef.current && metrics && !inStorybookTestRunner()) {
            chart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
                type: 'line',
                data: {
                    labels: metrics.dates,
                    datasets: [
                        {
                            label: 'events processed successfully',
                            data: metrics.successes,
                            borderColor: '',
                            ...colorConfig('data-color-1'),
                        },
                        {
                            label: 'events failed',
                            data: metrics.failures,
                            ...colorConfig('data-color-5'),
                        },
                    ],
                },
                options: {
                    scales: {
                        x: {
                            ticks: {
                                maxRotation: 0,
                            },
                            grid: {
                                display: false,
                            },
                        },
                        y: {
                            beginAtZero: true,
                        },
                    },
                    plugins: {
                        // @ts-expect-error Types of library are out of date
                        crosshair: false,
                        legend: {
                            display: false,
                        },
                    },
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        axis: 'x',
                        intersect: false,
                    },
                },
            })

            return () => {
                chart?.destroy()
            }
        }
    }, [metrics])

    if (metricsLoading || !metrics) {
        return <LemonSkeleton className="AppMetricsGraph border rounded p-6" />
    }

    return (
        <div className="AppMetricsGraph border rounded p-6">
            <canvas ref={canvasRef} />
        </div>
    )
}

function colorConfig(baseColorVar: string): Partial<ChartDataset<'line', any>> {
    const mainColor = getColorVar(baseColorVar)

    return {
        borderColor: mainColor,
        hoverBorderColor: lightenDarkenColor(mainColor, -20),
        hoverBackgroundColor: lightenDarkenColor(mainColor, -20),
        backgroundColor: mainColor,
        fill: false,
        borderWidth: 2,
        pointRadius: 0,
    }
}

function ErrorsOverview({ pluginConfigId }: { pluginConfigId: number }): JSX.Element {
    const logic = appMetricsLogic({ pluginConfigId })
    const { appMetricsResponse, appMetricsResponseLoading } = useValues(logic)
    const { openErrorDetailsModal } = useActions(logic)

    return (
        <>
            <ErrorDetailsModal pluginConfigId={pluginConfigId} />
            <LemonTable
                dataSource={appMetricsResponse?.errors || []}
                loading={appMetricsResponseLoading}
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
                                        openErrorDetailsModal(errorSummary.error_type)
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
                        <b>No errors! 🥳</b>
                        <p className="m-0">
                            If this app has any errors in the future, this table will contain information to help solve
                            the issue.
                        </p>
                    </div>
                }
            />
        </>
    )
}

function ErrorDetailsModal({ pluginConfigId }: { pluginConfigId: number }): JSX.Element {
    const logic = appMetricsLogic({ pluginConfigId })
    // const { appMetricsResponse, appMetricsResponseLoading } = useValues(logic)
    const { errorDetails, errorDetailsModalError, errorDetailsLoading } = useValues(logic)
    const { closeErrorDetailsModal } = useActions(logic)
    const [page, setPage] = useState(0)

    const activeErrorDetails: AppMetricErrorDetail = errorDetails[page]

    return (
        <LemonModal
            isOpen={!!errorDetailsModalError}
            onClose={closeErrorDetailsModal}
            title={errorDetailsModalError}
            width={'min(50vw, 80rem)'}
            description={<span>{activeErrorDetails?.error_details?.error.message?.substring(0, 200)}</span>}
            footer={
                <div className="flex items-center justify-end gap-1 h-">
                    {errorDetailsLoading ? (
                        <LemonSkeleton className="h-10" />
                    ) : (
                        <>
                            <span>
                                {page + 1} of {errorDetails.length} sample{errorDetails.length > 1 ? 's' : ''}
                            </span>
                            <LemonButton
                                icon={<IconChevronLeft />}
                                onClick={() => setPage(page - 1)}
                                disabledReason={page == 0 ? 'First page' : undefined}
                            />
                            <LemonButton
                                icon={<IconChevronRight />}
                                onClick={() => setPage(page + 1)}
                                disabledReason={page == errorDetails.length - 1 ? 'Last page' : undefined}
                            />
                        </>
                    )}
                </div>
            }
        >
            {!errorDetailsModalError || errorDetailsLoading ? (
                <LemonSkeleton className="h-10" />
            ) : (
                // eslint-disable-next-line react/forbid-dom-props
                <div className="flex flex-col space-y-2" style={{ height: '80vh' }}>
                    <div>
                        <LemonLabel>When:</LemonLabel> <TZLabel time={activeErrorDetails.timestamp} showSeconds />
                    </div>

                    {activeErrorDetails.error_details.eventCount && (
                        <div>
                            <LemonLabel>Event Count</LemonLabel>
                            <div>{activeErrorDetails.error_details.eventCount}</div>
                        </div>
                    )}

                    {activeErrorDetails.error_details.error.message && (
                        <CollapsibleSection title="Error message" defaultIsExpanded={true}>
                            <CodeSnippet wrap language={Language.JavaScript}>
                                {activeErrorDetails.error_details.error.message}
                            </CodeSnippet>
                        </CollapsibleSection>
                    )}

                    {activeErrorDetails.error_details.event && (
                        <CollapsibleSection title="Event payload" defaultIsExpanded={false}>
                            <CodeSnippet wrap language={Language.JSON}>
                                {JSON.stringify(activeErrorDetails.error_details.event, null, 2)}
                            </CodeSnippet>
                        </CollapsibleSection>
                    )}

                    {activeErrorDetails.error_details.error.stack && (
                        <CollapsibleSection title="Stack trace" defaultIsExpanded={false}>
                            <CodeSnippet wrap language={Language.JavaScript}>
                                {activeErrorDetails.error_details.error.stack}
                            </CodeSnippet>
                        </CollapsibleSection>
                    )}
                </div>
            )}
        </LemonModal>
    )
}

function CollapsibleSection(props: {
    title: string
    defaultIsExpanded: boolean
    children: React.ReactNode
}): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(props.defaultIsExpanded)

    return (
        <div className="bg-mid border rounded">
            <LemonButton
                status="stealth"
                fullWidth
                onClick={() => setIsExpanded(!isExpanded)}
                sideIcon={isExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                title={isExpanded ? 'Show less' : 'Show more'}
                className="bg-mid"
            >
                {props.title}
            </LemonButton>
            {isExpanded && <div className="bg-bg-light p-2">{props.children}</div>}
        </div>
    )
}
