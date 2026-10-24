import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect, LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { TIME_RANGE_LABELS, TimeRange, applicationObservabilityLogic } from './applicationObservabilityLogic'
import type { ServiceHealthApi, ServiceHealthStatusEnumApi } from './generated/api.schemas'

export const scene: SceneExport = {
    component: ApplicationObservabilityScene,
    logic: applicationObservabilityLogic,
}

const STATUS_LABEL: Record<ServiceHealthStatusEnumApi, string> = {
    good: 'Healthy',
    warning: 'Watch',
    serious: 'Failing',
    critical: 'Confirmed',
}

const STATUS_TAG: Record<ServiceHealthStatusEnumApi, 'success' | 'warning' | 'danger'> = {
    good: 'success',
    warning: 'warning',
    serious: 'danger',
    critical: 'danger',
}

export function formatRate(perSecond: number | null): string {
    if (perSecond === null) {
        return '—'
    }
    if (perSecond >= 1000) {
        return `${(perSecond / 1000).toFixed(1)}k/s`
    }
    if (perSecond >= 10) {
        return `${Math.round(perSecond)}/s`
    }
    if (perSecond >= 0.1) {
        return `${perSecond.toFixed(1)}/s`
    }
    return `${(perSecond * 60).toFixed(1)}/min`
}

export function formatPercent(fraction: number | null): string {
    if (fraction === null) {
        return '—'
    }
    const pct = fraction * 100
    return `${pct.toFixed(pct >= 10 ? 0 : pct >= 1 ? 1 : 2)}%`
}

export function formatMs(ms: number | null): string {
    if (ms === null) {
        return '—'
    }
    return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`
}

function Sparkline({ values }: { values: number[] }): JSX.Element {
    const width = 72
    const height = 18
    const max = Math.max(1, ...values)
    const points = values
        .map((value, index) => {
            const x = (index / Math.max(1, values.length - 1)) * (width - 2) + 1
            const y = height - 1 - (value / max) * (height - 2)
            return `${x.toFixed(1)},${y.toFixed(1)}`
        })
        .join(' ')
    return (
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" className="block">
            <polyline points={points} fill="none" stroke="currentColor" strokeWidth={1.5} className="text-muted" />
        </svg>
    )
}

export function ApplicationObservabilityScene(): JSX.Element {
    const { services, servicesHealthLoading, environments, resolvedEnvironment, timeRange, attentionCount } =
        useValues(applicationObservabilityLogic)
    const { setEnvironment, setTimeRange } = useActions(applicationObservabilityLogic)

    const columns: LemonTableColumns<ServiceHealthApi> = [
        {
            title: 'Service',
            key: 'service_name',
            render: (_, row) => <span className="font-semibold">{row.service_name}</span>,
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, row) => <LemonTag type={STATUS_TAG[row.status]}>{STATUS_LABEL[row.status]}</LemonTag>,
        },
        {
            title: 'Requests',
            key: 'request_rate',
            align: 'right',
            render: (_, row) => <span className="font-mono">{formatRate(row.health.request_rate)}</span>,
        },
        {
            title: 'Errors',
            key: 'error_rate',
            align: 'right',
            render: (_, row) => <span className="font-mono">{formatPercent(row.health.error_rate)}</span>,
        },
        {
            title: 'p95',
            key: 'p95_ms',
            align: 'right',
            render: (_, row) => <span className="font-mono">{formatMs(row.health.p95_ms)}</span>,
        },
        {
            title: 'Trend',
            key: 'sparkline',
            render: (_, row) => <Sparkline values={row.sparkline} />,
        },
        {
            title: 'Open in',
            key: 'links',
            render: (_, row) => (
                <span className="flex gap-2">
                    <Link
                        to={`${urls.tracing()}?serviceNames=${encodeURIComponent(row.service_name)}&date_from=${timeRange}`}
                    >
                        Traces
                    </Link>
                    <Link
                        to={`${urls.logs()}?service_name=${encodeURIComponent(row.service_name)}&date_from=${timeRange}`}
                    >
                        Logs
                    </Link>
                </span>
            ),
        },
    ]

    const attentionMessage =
        attentionCount > 0
            ? `${attentionCount} ${attentionCount === 1 ? 'service needs' : 'services need'} attention in ${resolvedEnvironment}`
            : `All quiet in ${resolvedEnvironment}`

    return (
        <SceneContent>
            <SceneTitleSection
                name="Application observability"
                description="One row per service, worst first, from the spans you already send."
                resourceType={{ type: 'tracing' }}
            />
            <div className="flex flex-wrap items-center gap-2">
                <LemonSelect
                    size="small"
                    value={resolvedEnvironment}
                    onChange={(value) => setEnvironment(value)}
                    options={(environments.length ? environments : [resolvedEnvironment]).map((env) => ({
                        value: env,
                        label: env,
                    }))}
                    data-attr="apm-environment"
                />
                <LemonSelect
                    size="small"
                    value={timeRange}
                    onChange={(value) => setTimeRange(value as TimeRange)}
                    options={(Object.keys(TIME_RANGE_LABELS) as TimeRange[]).map((value) => ({
                        value,
                        label: TIME_RANGE_LABELS[value],
                    }))}
                    data-attr="apm-time-range"
                />
                <span className="text-muted text-xs">Refreshes every 5 minutes</span>
            </div>
            {!servicesHealthLoading && services.length > 0 && (
                <LemonBanner type={attentionCount > 0 ? 'warning' : 'success'}>{attentionMessage}</LemonBanner>
            )}
            <LemonTable
                columns={columns}
                dataSource={services}
                rowKey="service_name"
                loading={servicesHealthLoading}
                emptyState="No spans in this environment and time range. Send traces to see services here."
                data-attr="apm-services-table"
            />
        </SceneContent>
    )
}
