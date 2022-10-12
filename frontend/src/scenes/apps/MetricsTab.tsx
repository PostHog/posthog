import React from 'react'
import { Card } from 'antd'
import { AppMetrics, AppMetricsTab } from './appMetricsSceneLogic'
import { DescriptionColumns } from './constants'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { humanFriendlyNumber } from 'lib/utils'
import { AppMetricsGraph } from './AppMetricsGraph'

export interface MetricsTabProps {
    tab: AppMetricsTab
    metrics: AppMetrics | null
    metricsLoading: boolean
}

export function MetricsTab({ tab, metrics, metricsLoading }: MetricsTabProps): JSX.Element {
    return (
        <div className="mt-4">
            <Card title="Metrics overview">
                <MetricsOverview tab={tab} metrics={metrics} metricsLoading={metricsLoading} />
            </Card>

            <Card title="graph" className="mt-4">
                <AppMetricsGraph tab={tab} metrics={metrics} metricsLoading={metricsLoading} />
            </Card>
        </div>
    )
}

export function MetricsOverview({ tab, metrics, metricsLoading }: MetricsTabProps): JSX.Element {
    return (
        <>
            <div>
                <div className="card-secondary">{DescriptionColumns[tab].successes}</div>
                <div>{renderNumber(metrics?.totals?.successes, metricsLoading)}</div>
            </div>
            {DescriptionColumns[tab].successes_on_retry && (
                <div>
                    <div className="card-secondary">{DescriptionColumns[tab].successes_on_retry}</div>
                    <div>{renderNumber(metrics?.totals?.successes_on_retry, metricsLoading)}</div>
                </div>
            )}
            <div>
                <div className="card-secondary">{DescriptionColumns[tab].failures}</div>
                <div>{renderNumber(metrics?.totals?.failures, metricsLoading)}</div>
            </div>
        </>
    )
}

function renderNumber(value: number | undefined, loading: boolean): JSX.Element {
    if (loading) {
        return <LemonSkeleton className="w-16" />
    }
    return <>{value ? humanFriendlyNumber(value) : value}</>
}
