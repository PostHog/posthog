import React from 'react'
import { Card } from 'antd'
import { AppErrorSummary, AppMetrics, appMetricsSceneLogic, AppMetricsTab } from './appMetricsSceneLogic'
import { DescriptionColumns } from './constants'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { humanFriendlyNumber } from 'lib/utils'
import { AppMetricsGraph } from './AppMetricsGraph'
import { LemonSelect } from 'lib/components/LemonSelect'
import { useActions, useValues } from 'kea'
import { LemonTable } from '../../lib/components/LemonTable'
import { TZLabel } from 'lib/components/TimezoneAware'

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
        <div className="mt-4">
            <Card
                title={
                    <div className="flex items-center justify-between gap-2">
                        <span>Metrics overview</span>
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
                }
            >
                <MetricsOverview
                    tab={tab}
                    metrics={appMetricsResponse?.metrics}
                    metricsLoading={appMetricsResponseLoading}
                />
            </Card>

            <Card title="Delivery trends" className="mt-4">
                <AppMetricsGraph
                    tab={tab}
                    metrics={appMetricsResponse?.metrics}
                    metricsLoading={appMetricsResponseLoading}
                />
            </Card>

            <Card title="Errors" className="mt-4">
                <ErrorsOverview errors={appMetricsResponse?.errors || []} loading={appMetricsResponseLoading} />
            </Card>
        </div>
    )
}

export function MetricsOverview({ tab, metrics, metricsLoading }: MetricsOverviewProps): JSX.Element {
    if (metricsLoading) {
        return <LemonSkeleton className="h-20" />
    }

    return (
        <>
            <div>
                <div className="card-secondary">{DescriptionColumns[tab].successes}</div>
                <div>{renderNumber(metrics?.totals?.successes)}</div>
            </div>
            {DescriptionColumns[tab].successes_on_retry && (
                <div>
                    <div className="card-secondary">{DescriptionColumns[tab].successes_on_retry}</div>
                    <div>{renderNumber(metrics?.totals?.successes_on_retry)}</div>
                </div>
            )}
            <div>
                <div className="card-secondary">{DescriptionColumns[tab].failures}</div>
                <div>{renderNumber(metrics?.totals?.failures)}</div>
            </div>
        </>
    )
}

export function ErrorsOverview({
    errors,
    loading,
}: {
    errors: Array<AppErrorSummary>
    loading?: boolean
}): JSX.Element {
    return (
        <LemonTable
            dataSource={errors}
            loading={loading}
            columns={[
                {
                    title: 'Error type',
                    dataIndex: 'error_type',
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
        />
    )
}

function renderNumber(value: number | undefined): JSX.Element {
    return <>{value ? humanFriendlyNumber(value) : value}</>
}
