import React from 'react'
import { Card } from 'antd'
import { AppMetrics, appMetricsSceneLogic, AppMetricsTab } from './appMetricsSceneLogic'
import { DescriptionColumns } from './constants'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { humanFriendlyNumber } from 'lib/utils'
import { AppMetricsGraph } from './AppMetricsGraph'
import { LemonSelect } from 'lib/components/LemonSelect'
import { useActions, useValues } from 'kea'

export interface MetricsTabProps {
    tab: AppMetricsTab
}

export interface MetricsOverviewProps {
    tab: AppMetricsTab
    metrics: AppMetrics | null
    metricsLoading: boolean
}

export function MetricsTab({ tab }: MetricsTabProps): JSX.Element {
    const { metrics, metricsLoading, dateFrom } = useValues(appMetricsSceneLogic)
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
                <MetricsOverview tab={tab} metrics={metrics} metricsLoading={metricsLoading} />
            </Card>

            <Card title="Delivery trends" className="mt-4">
                <AppMetricsGraph tab={tab} metrics={metrics} metricsLoading={metricsLoading} />
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

function renderNumber(value: number | undefined): JSX.Element {
    return <>{value ? humanFriendlyNumber(value) : value}</>
}
