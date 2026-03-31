import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonButton, LemonInput, LemonLabel, LemonModal, Link } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { urls } from 'scenes/urls'

import { tagsModel } from '~/models/tagsModel'
import { ExperimentMetric, NodeKind } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import { MetricConversionWindow } from '../ExperimentForm/MetricsPanel/MetricConversionWindow'
import { MetricEventDetails } from '../ExperimentForm/MetricsPanel/MetricEventDetails'
import { MetricGoal } from '../ExperimentForm/MetricsPanel/MetricGoal'
import { MetricOutlierHandling } from '../ExperimentForm/MetricsPanel/MetricOutlierHandling'
import { MetricStepOrder } from '../ExperimentForm/MetricsPanel/MetricStepOrder'
import { getDefaultMetricTitle, getMetricTag } from '../MetricsView/shared/utils'
import { InlineTagEditor } from '../SharedMetrics/InlineTagEditor'
import { SharedMetric } from '../SharedMetrics/sharedMetricLogic'
import { sharedMetricsLogic } from '../SharedMetrics/sharedMetricsLogic'
import { matchesSharedMetricSearch } from '../utils'
import { MetricContext } from './experimentMetricModalLogic'
import { sharedMetricModalLogic } from './sharedMetricModalLogic'

function MetricSummary({ metric }: { metric: SharedMetric }): JSX.Element {
    const experimentMetric = metric.query as ExperimentMetric

    return (
        <div className="border rounded bg-surface-primary p-4">
            <div className="space-y-3">
                <div className="flex-1 min-w-0 gap-2">
                    <div className="flex items-center gap-2 mb-1">
                        <span className="font-semibold text-sm break-words">
                            {metric.name || getDefaultMetricTitle(experimentMetric)}
                        </span>
                        <Link
                            target="_blank"
                            className="font-semibold flex items-center"
                            to={urls.experimentsSharedMetric(metric.id)}
                        >
                            <IconOpenInNew fontSize="18" />
                        </Link>
                    </div>
                    {metric.description && <p className="text-xs text-muted m-0 mb-2">{metric.description}</p>}
                    <MetricEventDetails metric={experimentMetric} />
                    <div className="flex items-center mt-2 gap-1">
                        <LemonTag type="muted" size="small">
                            {getMetricTag(experimentMetric)}
                        </LemonTag>
                        <LemonTag type="option" size="small">
                            Shared metric
                        </LemonTag>
                    </div>
                </div>

                <div className="border-t border-border" />

                <div className="space-y-1">
                    <MetricGoal metric={experimentMetric} />
                    <MetricConversionWindow metric={experimentMetric} />
                    <MetricStepOrder metric={experimentMetric} />
                    <MetricOutlierHandling metric={experimentMetric} />
                </div>
            </div>
        </div>
    )
}

export function SharedMetricModal({
    experiment,
    onSave,
    onDelete,
}: {
    experiment: Experiment
    onSave: (metrics: SharedMetric[], context: MetricContext) => void
    onDelete: (metric: SharedMetric, context: MetricContext) => void
}): JSX.Element | null {
    const { isModalOpen, context, compatibleSharedMetrics, sharedMetricId, isCreateMode, isEditMode, searchTerm } =
        useValues(sharedMetricModalLogic)
    const { closeSharedMetricModal, setSearchTerm, updateSharedMetricTags } = useActions(sharedMetricModalLogic)
    const { savingTagsMetricId } = useValues(sharedMetricsLogic)
    const { tags: allTags } = useValues(tagsModel)

    const [selectedMetricIds, setSelectedMetricIds] = useState<SharedMetric['id'][]>([])

    if (!compatibleSharedMetrics) {
        return null
    }

    const addSharedMetricDisabledReason = (): string | undefined => {
        if (selectedMetricIds.length === 0) {
            return 'Please select at least one metric'
        }
    }

    const closeModal = (): void => {
        setSelectedMetricIds([])
        closeSharedMetricModal()
    }

    const availableSharedMetrics = compatibleSharedMetrics.filter(
        (metric: SharedMetric) =>
            !experiment.saved_metrics.some((savedMetric) => savedMetric.saved_metric === metric.id)
    )

    const searchLower = searchTerm.toLowerCase()
    const filteredMetrics = searchTerm
        ? availableSharedMetrics.filter((metric) => matchesSharedMetricSearch(metric, searchLower))
        : availableSharedMetrics

    const availableTags = Array.from(
        new Set(filteredMetrics.flatMap((metric: SharedMetric) => metric.tags ?? []).filter(Boolean))
    ).sort()

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeModal}
            maxWidth={800}
            title={isCreateMode ? 'Select one or more shared metrics' : 'Shared metric'}
            footer={
                <div className="flex justify-between w-full">
                    <div>
                        {isEditMode && (
                            <LemonButton
                                status="danger"
                                onClick={() => {
                                    const metric = compatibleSharedMetrics.find((m) => m.id === sharedMetricId)
                                    if (!metric) {
                                        return
                                    }

                                    onDelete(metric, context)
                                }}
                                type="secondary"
                            >
                                Remove from experiment
                            </LemonButton>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <LemonButton onClick={closeModal} type="secondary">
                            Cancel
                        </LemonButton>
                        {/* Changing the existing metric is a pain because saved metrics are stored separately */}
                        {/* Only allow deletion for now */}
                        {isCreateMode && (
                            <LemonButton
                                onClick={() => {
                                    const metrics = selectedMetricIds
                                        .map((metricId) => compatibleSharedMetrics.find((m) => m.id === metricId))
                                        .filter((metric): metric is SharedMetric => metric !== undefined)

                                    onSave(metrics, context)
                                    setSelectedMetricIds([])
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
            {isCreateMode && (
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
                            <LemonInput
                                type="search"
                                placeholder="Search shared metrics..."
                                value={searchTerm}
                                onChange={setSearchTerm}
                                fullWidth
                            />
                            <div className="flex flex-wrap gap-2">
                                <LemonLabel>Quick select:</LemonLabel>
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    onClick={() => {
                                        setSelectedMetricIds(filteredMetrics.map((metric: SharedMetric) => metric.id))
                                    }}
                                >
                                    All
                                </LemonButton>
                                {selectedMetricIds.length > 0 && (
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        onClick={() => {
                                            setSelectedMetricIds([])
                                        }}
                                    >
                                        Clear
                                    </LemonButton>
                                )}
                                {availableTags.map((tag: string, index: number) => (
                                    <LemonButton
                                        key={index}
                                        size="xsmall"
                                        type="secondary"
                                        onClick={() => {
                                            setSelectedMetricIds(
                                                filteredMetrics
                                                    .filter((metric: SharedMetric) => metric.tags?.includes(tag))
                                                    .map((metric: SharedMetric) => metric.id)
                                            )
                                        }}
                                    >
                                        {tag}
                                    </LemonButton>
                                ))}
                            </div>
                            <LemonTable
                                dataSource={filteredMetrics}
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
                                    {
                                        title: 'Tags',
                                        dataIndex: 'tags' as keyof SharedMetric,
                                        key: 'tags',
                                        render: (_: any, metric: SharedMetric) => (
                                            <InlineTagEditor
                                                metric={metric}
                                                allTags={allTags}
                                                onSave={(newTags) => updateSharedMetricTags(metric.id, newTags)}
                                                saving={savingTagsMetricId === metric.id}
                                            />
                                        ),
                                    },
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
                                        <Link to={`${urls.experiments()}?tab=shared-metrics`} target="_blank">
                                            See all shared metrics
                                        </Link>
                                    </div>
                                }
                            />
                        </>
                    ) : (
                        <LemonBanner className="w-full" type="info">
                            <div className="mb-2">
                                {compatibleSharedMetrics.length > 0
                                    ? 'All of your shared metrics are already in this experiment.'
                                    : "You don't have any shared metrics that match the experiment type. Shared metrics let you create reusable metrics that you can quickly add to any experiment."}
                            </div>
                            <Link to={urls.experimentsSharedMetric('new')} target="_blank">
                                New shared metric
                            </Link>
                        </LemonBanner>
                    )}
                </div>
            )}

            {isEditMode &&
                (() => {
                    const metric = compatibleSharedMetrics.find((m) => m.id === sharedMetricId)
                    return metric ? <MetricSummary metric={metric} /> : null
                })()}
        </LemonModal>
    )
}
