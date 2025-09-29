import { useActions, useValues } from 'kea'

import { IconList, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { modalsLogic } from '../../modalsLogic'
import { createExperimentLogic } from '../createExperimentLogic'

interface MetricCardProps {
    metric: any
    onRemove: () => void
    isSecondary?: boolean
}

const MetricCard = ({ metric, onRemove, isSecondary = false }: MetricCardProps): JSX.Element => {
    const getMetricTypeTag = (metric: any): string => {
        // This would need to be implemented based on metric type
        return metric.query?.kind || 'Custom'
    }

    return (
        <div className="border rounded p-3 bg-surface-light">
            <div className="flex justify-between items-start">
                <div className="flex-1 min-w-0">
                    <div className="font-semibold mb-1 text-sm">{metric.name || 'Untitled Metric'}</div>
                    <div className="flex gap-1 mb-2">
                        <LemonTag type="muted" size="small">
                            {getMetricTypeTag(metric)}
                        </LemonTag>
                        {isSecondary && (
                            <LemonTag type="option" size="small">
                                Secondary
                            </LemonTag>
                        )}
                    </div>
                    {metric.description && <div className="text-xs text-muted">{metric.description}</div>}
                </div>
                <LemonButton icon={<IconTrash />} size="xsmall" onClick={onRemove} tooltip="Remove metric" noPadding />
            </div>
        </div>
    )
}

interface MetricsSectionProps {
    title: string
    description: string
    metrics: any[]
    onAddMetric: () => void
    onRemoveMetric: (metricUuid: string) => void
    onReorderMetrics: () => void
    isSecondary?: boolean
    emptyStateText: string
}

const MetricsSection = ({
    title,
    description,
    metrics,
    onAddMetric,
    onRemoveMetric,
    onReorderMetrics,
    isSecondary = false,
    emptyStateText,
}: MetricsSectionProps): JSX.Element => {
    return (
        <div className="space-y-3">
            <div className="flex justify-between items-start">
                <div>
                    <h3 className="font-semibold text-sm flex items-center gap-2">
                        {isSecondary ? '📊' : '🎯'} {title}
                    </h3>
                    <p className="text-xs text-muted mt-1">{description}</p>
                </div>
                <div className="flex gap-2">
                    {metrics.length > 1 && (
                        <LemonButton
                            icon={<IconList />}
                            size="xsmall"
                            onClick={onReorderMetrics}
                            tooltip="Reorder metrics"
                        >
                            Reorder
                        </LemonButton>
                    )}
                    <LemonButton icon={<IconPlus />} type="secondary" size="xsmall" onClick={onAddMetric}>
                        Add {isSecondary ? 'secondary' : 'primary'}
                    </LemonButton>
                </div>
            </div>

            {metrics.length === 0 ? (
                <div className="border border-dashed rounded p-4 text-center bg-surface-light">
                    <div className="text-sm text-muted mb-2">{emptyStateText}</div>
                    <LemonButton type="primary" size="small" icon={<IconPlus />} onClick={onAddMetric}>
                        Add {isSecondary ? 'secondary' : 'primary'} metric
                    </LemonButton>
                </div>
            ) : (
                <div className="space-y-2">
                    {metrics.map((metric, index) => (
                        <MetricCard
                            key={metric.uuid || index}
                            metric={metric}
                            onRemove={() => onRemoveMetric(metric.uuid)}
                            isSecondary={isSecondary}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}

export function MetricsPanel(): JSX.Element {
    const { primaryMetrics, secondaryMetrics, hasPrimaryMetrics } = useValues(createExperimentLogic)

    const { removePrimaryMetric, removeSecondaryMetric } = useActions(createExperimentLogic)

    const {
        openPrimaryMetricSourceModal,
        openSecondaryMetricSourceModal,
        openPrimaryMetricsReorderModal,
        openSecondaryMetricsReorderModal,
    } = useActions(modalsLogic)

    const handleAddPrimaryMetric = (): void => {
        openPrimaryMetricSourceModal()
    }

    const handleAddSecondaryMetric = (): void => {
        openSecondaryMetricSourceModal()
    }

    const handleReorderPrimaryMetrics = (): void => {
        openPrimaryMetricsReorderModal()
    }

    const handleReorderSecondaryMetrics = (): void => {
        openSecondaryMetricsReorderModal()
    }

    return (
        <div className="space-y-6">
            <div>
                <div className="text-sm text-muted mb-4">
                    Define the primary and secondary metrics you want to track in this experiment. Primary metrics are
                    the key success indicators, while secondary metrics provide additional insights.
                </div>

                {!hasPrimaryMetrics && (
                    <LemonBanner type="info" className="mb-4">
                        <strong>Start with a primary metric.</strong> Primary metrics are essential for measuring
                        experiment success and determining statistical significance.
                    </LemonBanner>
                )}
            </div>

            {/* Primary Metrics Section */}
            <MetricsSection
                title="Primary Metrics"
                description="Essential metrics that determine experiment success"
                metrics={primaryMetrics}
                onAddMetric={handleAddPrimaryMetric}
                onRemoveMetric={removePrimaryMetric}
                onReorderMetrics={handleReorderPrimaryMetrics}
                isSecondary={false}
                emptyStateText="No primary metrics defined yet"
            />

            {/* Secondary Metrics Section */}
            <MetricsSection
                title="Secondary Metrics"
                description="Additional metrics for deeper insights (optional)"
                metrics={secondaryMetrics}
                onAddMetric={handleAddSecondaryMetric}
                onRemoveMetric={removeSecondaryMetric}
                onReorderMetrics={handleReorderSecondaryMetrics}
                isSecondary={true}
                emptyStateText="No secondary metrics defined yet"
            />
        </div>
    )
}
