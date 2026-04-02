import { useActions } from 'kea'

import { IconCopy, IconPencil } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTag } from '@posthog/lemon-ui'

import { METRIC_CONTEXTS, experimentMetricModalLogic } from 'scenes/experiments/Metrics/experimentMetricModalLogic'
import { sharedMetricModalLogic } from 'scenes/experiments/Metrics/sharedMetricModalLogic'
import { modalsLogic } from 'scenes/experiments/modalsLogic'
import { urls } from 'scenes/urls'

import type {
    Breakdown,
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
} from '~/queries/schema/schema-general'
import { NodeKind } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { LegacyMetricTitle } from './LegacyMetricTitle'

/**
 * @deprecated
 * This component supports legacy experiment metrics (ExperimentTrendsQuery/ExperimentFunnelsQuery).
 * Frozen copy for legacy experiments - do not modify.
 */

function getMetricTag(metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery): string {
    if (metric.kind === NodeKind.ExperimentMetric) {
        return metric.metric_type.charAt(0).toUpperCase() + metric.metric_type.slice(1).toLowerCase()
    } else if (metric.kind === NodeKind.ExperimentFunnelsQuery) {
        return 'Funnel'
    }
    return 'Trend'
}

/**
 * @deprecated
 * This component supports legacy experiment metrics (ExperimentTrendsQuery/ExperimentFunnelsQuery).
 * Frozen copy for legacy experiments - do not modify.
 */
export const LegacyMetricHeader = ({
    displayOrder,
    metric,
    metricType,
    isPrimaryMetric,
    onDuplicateMetricClick,
    readOnly,
}: {
    displayOrder?: number
    metric: ExperimentTrendsQuery | ExperimentFunnelsQuery
    metricType: any
    isPrimaryMetric: boolean
    experiment: Experiment
    onDuplicateMetricClick: (metric: ExperimentMetric) => void
    onBreakdownChange: (breakdown: Breakdown) => void
    readOnly?: boolean
}): JSX.Element => {
    const {
        openPrimaryMetricModal,
        openSecondaryMetricModal,
        openPrimarySharedMetricModal,
        openSecondarySharedMetricModal,
    } = useActions(modalsLogic)

    const { openExperimentMetricModal } = useActions(experimentMetricModalLogic)
    const { openSharedMetricModal } = useActions(sharedMetricModalLogic)

    return (
        <div className="text-xs font-semibold flex flex-col justify-between h-full">
            <div className="deprecated-space-y-1">
                <div className="flex items-start justify-between gap-2 min-w-0">
                    <div className="text-xs font-semibold flex items-start min-w-0 flex-1">
                        {displayOrder !== undefined && <span className="mr-1 flex-shrink-0">{displayOrder + 1}.</span>}
                        <div className="min-w-0 flex-1">
                            <LegacyMetricTitle metric={metric} metricType={metricType} />
                        </div>
                    </div>
                    {!readOnly && (
                        <div className="flex flex-col gap-1 flex-shrink-0 items-end">
                            <div className="flex gap-1">
                                <LemonButton
                                    className="flex-shrink-0"
                                    type="secondary"
                                    size="xsmall"
                                    icon={<IconPencil fontSize="12" />}
                                    tooltip="Edit"
                                    onClick={() => {
                                        if (metric.isSharedMetric) {
                                            const openSharedModal = isPrimaryMetric
                                                ? openPrimarySharedMetricModal
                                                : openSecondarySharedMetricModal
                                            openSharedModal(metric.sharedMetricId)

                                            openSharedMetricModal(
                                                METRIC_CONTEXTS[isPrimaryMetric ? 'primary' : 'secondary'],
                                                metric.sharedMetricId
                                            )
                                        } else {
                                            const openMetricModal = isPrimaryMetric
                                                ? openPrimaryMetricModal
                                                : openSecondaryMetricModal
                                            if (metric.uuid) {
                                                openMetricModal(metric.uuid)
                                            }

                                            openExperimentMetricModal(
                                                METRIC_CONTEXTS[isPrimaryMetric ? 'primary' : 'secondary'],
                                                metric
                                            )
                                        }
                                    }}
                                />
                                <LemonButton
                                    className="flex-shrink-0"
                                    type="secondary"
                                    size="xsmall"
                                    icon={<IconCopy fontSize="12" />}
                                    tooltip="Duplicate"
                                    onClick={() => {
                                        if (metric.isSharedMetric) {
                                            LemonDialog.open({
                                                title: 'Duplicate this shared metric?',
                                                content: (
                                                    <div className="text-sm text-secondary max-w-lg">
                                                        <p>
                                                            We'll take you to the form to customize and save this
                                                            metric. Your new version will appear in your shared metrics,
                                                            ready to be added to your experiment.
                                                        </p>
                                                    </div>
                                                ),
                                                primaryButton: {
                                                    children: 'Duplicate metric',
                                                    to: urls.experimentsSharedMetric(
                                                        metric.sharedMetricId,
                                                        'duplicate'
                                                    ),
                                                    type: 'primary',
                                                    size: 'small',
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                    type: 'tertiary',
                                                    size: 'small',
                                                },
                                            })

                                            return
                                        }

                                        // regular metrics just get duplicated
                                        onDuplicateMetricClick(metric)
                                    }}
                                />
                            </div>
                        </div>
                    )}
                </div>
                <div className="deprecated-space-x-1">
                    <LemonTag type="muted" size="small">
                        {getMetricTag(metric)}
                    </LemonTag>
                    {metric.goal === 'decrease' && (
                        <LemonTag type="highlight" size="small">
                            Goal: Decrease
                        </LemonTag>
                    )}
                    {metric.isSharedMetric && (
                        <LemonTag type="option" size="small">
                            Shared
                        </LemonTag>
                    )}
                </div>
            </div>
        </div>
    )
}
