import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonLabel, LemonModal, Link } from '@posthog/lemon-ui'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { pluralize } from 'lib/utils/strings'
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
        displayedMetrics,
        availableTags,
        filterTags,
        searchTerm,
        sharedMetricsResponseLoading,
        isLoadingAllSharedMetrics,
        hasAnyCompatibleSharedMetrics,
        selectedMetricIds,
    } = useValues(sharedMetricModalLogic)
    const {
        closeSharedMetricModal,
        setSearchTerm,
        toggleSelectedMetricId,
        setSelectedMetricIds,
        clearSelectedMetricIds,
        selectByTag,
        clearFilterTags,
    } = useActions(sharedMetricModalLogic)
    const { savingTagsMetricId } = useValues(sharedMetricsLogic)
    const { updateSharedMetricTags } = useActions(sharedMetricsLogic)
    const { tags: allTags } = useValues(tagsModel)

    if (!compatibleSharedMetrics) {
        return null
    }

    const addSharedMetricDisabledReason = (): string | undefined => {
        if (selectedMetricIds.length === 0) {
            return 'Please select at least one metric'
        }
    }

    const closeModal = (): void => {
        clearSelectedMetricIds()
        closeSharedMetricModal()
    }

    const savedMetrics = experiment.saved_metrics ?? []
    const alreadyAddedIdsList = savedMetrics.map((savedMetric) => savedMetric.saved_metric)
    const alreadyAddedIds = new Set(alreadyAddedIdsList)

    // Ids of the currently displayed metrics (after tag filtering) that can still be added.
    const displayedSelectableIds = displayedMetrics
        .filter((metric: SharedMetric) => !alreadyAddedIds.has(metric.id))
        .map((metric: SharedMetric) => metric.id)

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
                                clearSelectedMetricIds()
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
                {hasAnyCompatibleSharedMetrics || sharedMetricsResponseLoading ? (
                    <>
                        {savedMetrics.length > 0 && (
                            <LemonBanner type="info">
                                {`${pluralize(savedMetrics.length, 'shared metric')} ${
                                    savedMetrics.length > 1 ? 'are' : 'is'
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
                        <div className="flex flex-wrap gap-2 items-center">
                            <LemonLabel>Quick select:</LemonLabel>
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                loading={isLoadingAllSharedMetrics}
                                disabledReason={
                                    displayedSelectableIds.length === 0 ? 'No metrics to select' : undefined
                                }
                                onClick={() => {
                                    // Add every currently displayed (tag-filtered) metric to the selection.
                                    setSelectedMetricIds(
                                        Array.from(new Set([...selectedMetricIds, ...displayedSelectableIds]))
                                    )
                                }}
                            >
                                All
                            </LemonButton>
                            {selectedMetricIds.length > 0 && (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    onClick={() => {
                                        clearSelectedMetricIds()
                                    }}
                                >
                                    Clear
                                </LemonButton>
                            )}
                        </div>
                        {availableTags.length > 0 && (
                            <div className="flex flex-wrap gap-2 items-center">
                                <LemonLabel>Select by tag:</LemonLabel>
                                {availableTags.map((tag: string) => (
                                    <LemonButton
                                        key={tag}
                                        size="xsmall"
                                        type="secondary"
                                        active={filterTags.includes(tag)}
                                        // Wait for every page so clicking a tag selects all of its metrics.
                                        disabledReason={isLoadingAllSharedMetrics ? 'Loading all metrics…' : undefined}
                                        onClick={() => {
                                            // Toggle this tag: selects (and shows) every metric carrying it, across
                                            // all pages — or deselects them if it was already active.
                                            selectByTag(tag, alreadyAddedIdsList)
                                        }}
                                    >
                                        {tag}
                                    </LemonButton>
                                ))}
                                {filterTags.length > 0 && (
                                    <LemonButton size="xsmall" type="tertiary" onClick={() => clearFilterTags()}>
                                        Show all
                                    </LemonButton>
                                )}
                            </div>
                        )}
                        <LemonTable
                            dataSource={displayedMetrics}
                            loading={sharedMetricsResponseLoading && displayedMetrics.length === 0}
                            emptyState={
                                filterTags.length > 0 ? (
                                    <div>No shared metrics match the selected tags.</div>
                                ) : (
                                    <div>No shared metrics match your search.</div>
                                )
                            }
                            columns={[
                                {
                                    title: '',
                                    key: 'checkbox',
                                    render: (_, metric: SharedMetric) => (
                                        <input
                                            type="checkbox"
                                            disabled={alreadyAddedIds.has(metric.id)}
                                            checked={selectedMetricIds.includes(metric.id)}
                                            onChange={() => {
                                                toggleSelectedMetricId(metric.id)
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
                                    {isLoadingAllSharedMetrics && displayedMetrics.length > 0 && (
                                        <span className="text-secondary text-xs">Loading all metrics…</span>
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
