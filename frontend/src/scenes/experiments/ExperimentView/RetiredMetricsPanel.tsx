import { useValues } from 'kea'

import { LemonBanner, LemonTag } from '@posthog/lemon-ui'

import { LemonTable } from 'lib/lemon-ui/LemonTable'

import {
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    NodeKind,
} from '~/queries/schema/schema-general'

import { experimentLogic } from '../experimentLogic'

type AnyMetric = ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery

interface MetricRow {
    label: string
    kind: string
}

const getSeriesLabel = (series?: { name?: string; event?: string | null }): string | undefined =>
    series?.name || series?.event || undefined

const toMetricRow = (metric: AnyMetric): MetricRow => {
    if (metric.kind === NodeKind.ExperimentTrendsQuery) {
        return {
            label: metric.name || getSeriesLabel(metric.count_query?.series?.[0]) || 'Untitled metric',
            kind: 'Trend',
        }
    }
    if (metric.kind === NodeKind.ExperimentFunnelsQuery) {
        const steps = metric.funnels_query?.series?.length ?? 0
        return {
            label: metric.name || getSeriesLabel(metric.funnels_query?.series?.[0]) || 'Untitled metric',
            kind: steps ? `Funnel, ${steps} steps` : 'Funnel',
        }
    }
    return { label: metric.name || 'Untitled metric', kind: 'Metric' }
}

const MetricTable = ({ title, metrics }: { title: string; metrics: AnyMetric[] }): JSX.Element | null => {
    if (!metrics.length) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <h3 className="mb-0">{title}</h3>
            <LemonTable
                dataSource={metrics.map(toMetricRow)}
                columns={[
                    { title: 'Metric', dataIndex: 'label' },
                    {
                        title: 'Type',
                        dataIndex: 'kind',
                        render: (kind) => (
                            <LemonTag size="small" type="muted">
                                {kind}
                            </LemonTag>
                        ),
                    },
                ]}
            />
        </div>
    )
}

export const RetiredMetricsPanel = (): JSX.Element => {
    const { experiment } = useValues(experimentLogic)

    const primaryMetrics: AnyMetric[] = [
        ...experiment.metrics,
        ...experiment.saved_metrics.filter((m) => m.metadata.type === 'primary').map((m) => m.query),
    ]
    const secondaryMetrics: AnyMetric[] = [
        ...experiment.metrics_secondary,
        ...experiment.saved_metrics.filter((m) => m.metadata.type === 'secondary').map((m) => m.query),
    ]

    return (
        <div className="flex flex-col gap-4">
            <LemonBanner type="warning">
                <div>
                    <strong>Results are no longer calculated for this experiment</strong>
                </div>
                <div>
                    It uses an older metric format that PostHog no longer supports. The metric definitions are kept
                    below for reference. To measure this again, create a new experiment.
                </div>
            </LemonBanner>
            <MetricTable title="Primary metrics" metrics={primaryMetrics} />
            <MetricTable title="Secondary metrics" metrics={secondaryMetrics} />
        </div>
    )
}
