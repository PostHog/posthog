import { LemonButton, LemonDialog, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ExperimentFunnelsQuery, ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import { Experiment, InsightType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { getDefaultFunnelsMetric, getDefaultTrendsMetric } from '../utils'
import { FunnelsMetricForm } from './FunnelsMetricForm'
import { TrendsMetricForm } from './TrendsMetricForm'
import { modalsLogic } from '../modalsLogic'

export function LegacyMetricModal({
    experimentId,
    isSecondary,
}: {
    experimentId: Experiment['id']
    isSecondary?: boolean
}): JSX.Element {
    const { experiment, experimentLoading, getInsightType, editingPrimaryMetricIndex, editingSecondaryMetricIndex } =
        useValues(experimentLogic({ experimentId }))
    const { updateExperimentMetrics, setExperiment, restoreUnmodifiedExperiment } = useActions(
        experimentLogic({ experimentId })
    )
    const { closePrimaryMetricModal, closeSecondaryMetricModal } = useActions(modalsLogic)
    const { isPrimaryMetricModalOpen, isSecondaryMetricModalOpen } = useValues(modalsLogic)

    const metricIdx = isSecondary ? editingSecondaryMetricIndex : editingPrimaryMetricIndex
    const metricsField = isSecondary ? 'metrics_secondary' : 'metrics'

    if (!metricIdx && metricIdx !== 0) {
        return <></>
    }

    const metrics = experiment[metricsField]
    const metric = metrics[metricIdx] as ExperimentTrendsQuery | ExperimentFunnelsQuery
    const insightType = getInsightType(metric)
    const funnelStepsLength = (metric as ExperimentFunnelsQuery)?.funnels_query?.series?.length || 0

    const onClose = (): void => {
        restoreUnmodifiedExperiment()
        isSecondary ? closeSecondaryMetricModal() : closePrimaryMetricModal()
    }

    return (
        <LemonModal
            isOpen={isSecondary ? isSecondaryMetricModalOpen : isPrimaryMetricModalOpen}
            onClose={onClose}
            width={1000}
            title="Edit experiment metric"
            footer={
                <div className="flex items-center w-full">
                    <LemonButton
                        type="secondary"
                        status="danger"
                        onClick={() => {
                            LemonDialog.open({
                                title: 'Delete this metric?',
                                content: <div className="text-sm text-secondary">This action cannot be undone.</div>,
                                primaryButton: {
                                    children: 'Delete',
                                    type: 'primary',
                                    onClick: () => {
                                        const newMetrics = metrics.filter((_, idx) => idx !== metricIdx)
                                        setExperiment({
                                            [metricsField]: newMetrics,
                                        })
                                        updateExperimentMetrics()
                                        isSecondary ? closeSecondaryMetricModal() : closePrimaryMetricModal()
                                    },
                                    size: 'small',
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                    type: 'tertiary',
                                    size: 'small',
                                },
                            })
                        }}
                    >
                        Delete
                    </LemonButton>
                    <div className="flex items-center gap-2 ml-auto">
                        <LemonButton form="edit-experiment-goal-form" type="secondary" onClick={onClose}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            disabledReason={
                                insightType === InsightType.FUNNELS &&
                                funnelStepsLength < 2 &&
                                'The experiment needs at least two funnel steps.'
                            }
                            form="edit-experiment-goal-form"
                            onClick={() => {
                                updateExperimentMetrics()
                                isSecondary ? closeSecondaryMetricModal() : closePrimaryMetricModal()
                            }}
                            type="primary"
                            loading={experimentLoading}
                            data-attr="create-annotation-submit"
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="flex items-center w-full gap-2 mb-4">
                <span>Metric type</span>
                <LemonSelect
                    data-attr="metrics-selector"
                    value={insightType}
                    onChange={(newInsightType) => {
                        setExperiment({
                            ...experiment,
                            [metricsField]: [
                                ...metrics.slice(0, metricIdx),
                                newInsightType === InsightType.TRENDS
                                    ? getDefaultTrendsMetric()
                                    : getDefaultFunnelsMetric(),
                                ...metrics.slice(metricIdx + 1),
                            ],
                        })
                    }}
                    options={[
                        { value: InsightType.TRENDS, label: <b>Trends</b> },
                        { value: InsightType.FUNNELS, label: <b>Funnels</b> },
                    ]}
                />
            </div>
            {insightType === InsightType.TRENDS ? (
                <TrendsMetricForm isSecondary={isSecondary} />
            ) : (
                <FunnelsMetricForm isSecondary={isSecondary} />
            )}
        </LemonModal>
    )
}
