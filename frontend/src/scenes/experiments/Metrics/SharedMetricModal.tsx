import { LemonBanner, LemonButton, LemonLabel, LemonModal, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { useState } from 'react'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import { AvailableFeature, Experiment } from '~/types'

import { EXPERIMENT_MAX_PRIMARY_METRICS, EXPERIMENT_MAX_SECONDARY_METRICS } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { MetricDisplayFunnels, MetricDisplayTrends } from '../ExperimentView/components'
import { modalsLogic } from '../modalsLogic'
import { SharedMetric } from '../SharedMetrics/sharedMetricLogic'

export function SharedMetricModal({
    experimentId,
    isSecondary,
}: {
    experimentId: Experiment['id']
    isSecondary?: boolean
}): JSX.Element {
    const {
        experiment,
        compatibleSharedMetrics,
        editingSharedMetricId,
        primaryMetricsLengthWithSharedMetrics,
        secondaryMetricsLengthWithSharedMetrics,
    } = useValues(experimentLogic({ experimentId }))
    const { addSharedMetricsToExperiment, removeSharedMetricFromExperiment, restoreUnmodifiedExperiment } = useActions(
        experimentLogic({ experimentId })
    )
    const { closePrimarySharedMetricModal, closeSecondarySharedMetricModal } = useActions(modalsLogic)
    const { isPrimarySharedMetricModalOpen, isSecondarySharedMetricModalOpen } = useValues(modalsLogic)

    const [selectedMetricIds, setSelectedMetricIds] = useState<SharedMetric['id'][]>([])
    const mode = editingSharedMetricId ? 'edit' : 'create'

    const { hasAvailableFeature } = useValues(userLogic)

    if (!compatibleSharedMetrics) {
        return <></>
    }

    const isOpen = isSecondary ? isSecondarySharedMetricModalOpen : isPrimarySharedMetricModalOpen
    const onClose = (): void => {
        restoreUnmodifiedExperiment()
        isSecondary ? closeSecondarySharedMetricModal() : closePrimarySharedMetricModal()
    }

    const addSharedMetricDisabledReason = (): string | undefined => {
        if (selectedMetricIds.length === 0) {
            return 'Please select at least one metric'
        }

        if (
            !isSecondary &&
            primaryMetricsLengthWithSharedMetrics + selectedMetricIds.length > EXPERIMENT_MAX_PRIMARY_METRICS
        ) {
            return `You can only add up to ${EXPERIMENT_MAX_PRIMARY_METRICS} primary metrics.`
        }

        if (
            isSecondary &&
            secondaryMetricsLengthWithSharedMetrics + selectedMetricIds.length > EXPERIMENT_MAX_SECONDARY_METRICS
        ) {
            return `You can only add up to ${EXPERIMENT_MAX_SECONDARY_METRICS} secondary metrics.`
        }
    }

    const availableSharedMetrics = compatibleSharedMetrics.filter(
        (metric: SharedMetric) =>
            !experiment.saved_metrics.some((savedMetric) => savedMetric.saved_metric === metric.id)
    )

    const availableTags = Array.from(
        new Set(
            availableSharedMetrics
                .filter((metric: SharedMetric) => metric.tags)
                .flatMap((metric: SharedMetric) => metric.tags)
                .filter(Boolean)
        )
    ).sort()

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={500}
            title={mode === 'create' ? 'Select one or more shared metrics' : 'Shared metric'}
            footer={
                <div className="flex justify-between w-full">
                    <div>
                        {editingSharedMetricId && (
                            <LemonButton
                                status="danger"
                                onClick={() => {
                                    removeSharedMetricFromExperiment(editingSharedMetricId)
                                    isSecondary ? closeSecondarySharedMetricModal() : closePrimarySharedMetricModal()
                                }}
                                type="secondary"
                            >
                                Remove from experiment
                            </LemonButton>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <LemonButton onClick={onClose} type="secondary">
                            Cancel
                        </LemonButton>
                        {/* Changing the existing metric is a pain because saved metrics are stored separately */}
                        {/* Only allow deletion for now */}
                        {mode === 'create' && (
                            <LemonButton
                                onClick={() => {
                                    addSharedMetricsToExperiment(selectedMetricIds, {
                                        type: isSecondary ? 'secondary' : 'primary',
                                    })
                                    isSecondary ? closeSecondarySharedMetricModal() : closePrimarySharedMetricModal()
                                }}
                                type="primary"
                                disabledReason={addSharedMetricDisabledReason()}
                            >
                                {selectedMetricIds.length < 2 ? 'Add metric' : 'Add metrics'}
                            </LemonButton>
                        )}
                    </div>
                </div>
            }
        >
            {mode === 'create' && (
                <div className="deprecated-space-y-2">
                    {availableSharedMetrics.length > 0 ? (
                        <>
                            {experiment.saved_metrics.length > 0 && (
                                <LemonBanner type="info">
                                    {`Hiding ${experiment.saved_metrics.length} shared ${
                                        experiment.saved_metrics.length > 1 ? 'metrics' : 'metric'
                                    } already in use with this experiment.`}
                                </LemonBanner>
                            )}
                            {hasAvailableFeature(AvailableFeature.TAGGING) && availableTags.length > 0 && (
                                <div className="flex flex-wrap gap-2">
                                    <LemonLabel>Quick select:</LemonLabel>
                                    {availableTags.map((tag: string, index: number) => (
                                        <LemonButton
                                            key={index}
                                            size="xsmall"
                                            type="secondary"
                                            onClick={() => {
                                                setSelectedMetricIds(
                                                    availableSharedMetrics
                                                        .filter((metric: SharedMetric) => metric.tags?.includes(tag))
                                                        .map((metric: SharedMetric) => metric.id)
                                                )
                                            }}
                                        >
                                            {tag}
                                        </LemonButton>
                                    ))}
                                </div>
                            )}
                            <LemonTable
                                dataSource={availableSharedMetrics}
                                columns={[
                                    {
                                        title: '',
                                        key: 'checkbox',
                                        render: (_, metric: SharedMetric) => (
                                            <input
                                                type="checkbox"
                                                checked={selectedMetricIds.includes(metric.id)}
                                                onChange={(e) => {
                                                    if (e.target.checked) {
                                                        setSelectedMetricIds([...selectedMetricIds, metric.id])
                                                    } else {
                                                        setSelectedMetricIds(
                                                            selectedMetricIds.filter((id) => id !== metric.id)
                                                        )
                                                    }
                                                }}
                                            />
                                        ),
                                    },
                                    {
                                        title: 'Name',
                                        dataIndex: 'name',
                                        key: 'name',
                                    },
                                    {
                                        title: 'Description',
                                        dataIndex: 'description',
                                        key: 'description',
                                    },
                                    ...(hasAvailableFeature(AvailableFeature.TAGGING)
                                        ? [
                                              {
                                                  title: 'Tags',
                                                  dataIndex: 'tags' as keyof SharedMetric,
                                                  key: 'tags',
                                                  render: (_: any, metric: SharedMetric) => (
                                                      <ObjectTags tags={metric.tags || []} staticOnly />
                                                  ),
                                              },
                                          ]
                                        : []),
                                    {
                                        title: 'Type',
                                        key: 'type',
                                        render: (_, metric: SharedMetric) => {
                                            if (metric.query.kind === NodeKind.ExperimentMetric) {
                                                return metric.query.metric_type
                                            }
                                            return metric.query.kind === NodeKind.ExperimentTrendsQuery
                                                ? 'Trend'
                                                : 'Funnel'
                                        },
                                    },
                                ]}
                                footer={
                                    <div className="flex items-center justify-center m-2">
                                        <LemonButton to={urls.experimentsSharedMetrics()} size="xsmall" type="tertiary">
                                            See all shared metrics
                                        </LemonButton>
                                    </div>
                                }
                            />
                        </>
                    ) : (
                        <LemonBanner
                            className="w-full"
                            type="info"
                            action={{
                                children: 'New shared metric',
                                to: urls.experimentsSharedMetric('new'),
                            }}
                        >
                            {compatibleSharedMetrics.length > 0
                                ? 'All of your shared metrics are already in this experiment.'
                                : "You don't have any shared metrics that match the experiment type. Shared metrics let you create reusable metrics that you can quickly add to any experiment."}
                        </LemonBanner>
                    )}
                </div>
            )}

            {editingSharedMetricId && (
                <div>
                    {(() => {
                        const metric = compatibleSharedMetrics.find((m: SharedMetric) => m.id === editingSharedMetricId)
                        if (!metric) {
                            return <></>
                        }

                        return (
                            <div className="deprecated-space-y-2">
                                <div className="flex items-center gap-2">
                                    <h3 className="font-semibold m-0 flex items-center">{metric.name}</h3>
                                    <Link
                                        target="_blank"
                                        className="font-semibold flex items-center"
                                        to={urls.experimentsSharedMetric(metric.id)}
                                    >
                                        <IconOpenInNew fontSize="18" />
                                    </Link>
                                </div>
                                {metric.description && <p className="mt-2">{metric.description}</p>}
                                {metric.query.kind === 'ExperimentTrendsQuery' && (
                                    <MetricDisplayTrends query={metric.query.count_query} />
                                )}
                                {metric.query.kind === 'ExperimentFunnelsQuery' && (
                                    <MetricDisplayFunnels query={metric.query.funnels_query} />
                                )}
                            </div>
                        )
                    })()}
                </div>
            )}
        </LemonModal>
    )
}
