import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonButton, LemonInput, LemonLabel, LemonModal, Link } from '@posthog/lemon-ui'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { pluralize } from 'lib/utils'
import { urls } from 'scenes/urls'

import { tagsModel } from '~/models/tagsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import { InlineTagEditor } from '../SharedMetrics/InlineTagEditor'
import { SharedMetric } from '../SharedMetrics/sharedMetricLogic'
import { sharedMetricsLogic } from '../SharedMetrics/sharedMetricsLogic'
import { MetricContext } from './experimentMetricModalLogic'
import { sharedMetricModalLogic } from './sharedMetricModalLogic'

export function SharedMetricModal({
    experiment,
    onSave,
}: {
    experiment: Experiment
    onSave: (metrics: SharedMetric[], context: MetricContext) => void
}): JSX.Element | null {
    const {
        isModalOpen,
        context,
        compatibleSharedMetrics,
        searchTerm,
        canLoadMore,
        sharedMetricsResponseLoading,
        hasAnyCompatibleSharedMetrics,
    } = useValues(sharedMetricModalLogic)
    const { closeSharedMetricModal, setSearchTerm, loadNextSharedMetrics } = useActions(sharedMetricModalLogic)
    const { savingTagsMetricId } = useValues(sharedMetricsLogic)
    const { updateSharedMetricTags } = useActions(sharedMetricsLogic)
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

    const alreadyAddedIds = new Set(experiment.saved_metrics.map((savedMetric) => savedMetric.saved_metric))

    // Already-added metrics stay visible but are not selectable.
    const selectableMetrics = compatibleSharedMetrics.filter((metric: SharedMetric) => !alreadyAddedIds.has(metric.id))

    /**
     * we need to get the tags from the metrics that can be added to the experiment
     */
    const availableTags = Array.from(
        new Set(selectableMetrics.flatMap((metric: SharedMetric) => metric.tags ?? []).filter(Boolean))
    ).sort()

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeModal}
            maxWidth={800}
            title="Select one or more shared metrics"
            footer={
                <div className="flex justify-between w-full">
                    <div className="flex gap-2">
                        <LemonButton onClick={closeModal} type="secondary">
                            Cancel
                        </LemonButton>
                        {/* Changing the existing metric is a pain because saved metrics are stored separately */}
                        {/* Only allow deletion for now */}
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
                    </div>
                </div>
            }
        >
            <div className="deprecated-space-y-2">
                {hasAnyCompatibleSharedMetrics ? (
                    <>
                        {experiment.saved_metrics.length > 0 && (
                            <LemonBanner type="info">
                                {`${pluralize(experiment.saved_metrics.length, 'shared metric')} ${
                                    experiment.saved_metrics.length > 1 ? 'are' : 'is'
                                } already in the experiment.`}
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
                                    setSelectedMetricIds(selectableMetrics.map((metric: SharedMetric) => metric.id))
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
                                            selectableMetrics
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
                            dataSource={compatibleSharedMetrics}
                            loading={sharedMetricsResponseLoading}
                            emptyState={<div>No shared metrics match your search.</div>}
                            columns={[
                                {
                                    title: '',
                                    key: 'checkbox',
                                    render: (_, metric: SharedMetric) => (
                                        <input
                                            type="checkbox"
                                            disabled={alreadyAddedIds.has(metric.id)}
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
                                    key: 'name',
                                    render: (_, metric: SharedMetric) => (
                                        <span>
                                            {metric.name}
                                            {alreadyAddedIds.has(metric.id) && (
                                                <span className="text-secondary ml-2">(already added)</span>
                                            )}
                                        </span>
                                    ),
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
                                        return metric.query.kind === NodeKind.ExperimentTrendsQuery ? 'Trend' : 'Funnel'
                                    },
                                },
                            ]}
                            footer={
                                <div className="flex flex-col items-center gap-2 m-2">
                                    {canLoadMore && (
                                        <LemonButton
                                            type="secondary"
                                            onClick={loadNextSharedMetrics}
                                            loading={sharedMetricsResponseLoading}
                                        >
                                            Load more metrics
                                        </LemonButton>
                                    )}
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
                            You don't have any shared metrics that match the experiment type. Shared metrics let you
                            create reusable metrics that you can quickly add to any experiment.
                        </div>
                        <Link to={urls.experimentsSharedMetric('new')} target="_blank">
                            New shared metric
                        </Link>
                    </LemonBanner>
                )}
            </div>
        </LemonModal>
    )
}
