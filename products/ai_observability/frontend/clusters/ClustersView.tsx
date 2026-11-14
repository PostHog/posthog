import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconQuestion, IconScatter } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSegmentedButton, LemonSelect, Spinner, Tooltip } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { dayjs } from 'lib/dayjs'

import { groupsModel } from '~/models/groupsModel'

import { TraceDrawerHost } from '../redesign/trace/TraceDrawerHost'
import { TraceDrawerRowsSync } from '../redesign/trace/TraceDrawerRowsHost'
import { clusteringConfigLogic } from './clusteringConfigLogic'
import { ClusteringEnabledSwitch } from './ClusteringEnabledSwitch'
import { ClusteringJobsButton } from './ClusteringJobsButton'
import { clusteringJobsLogic } from './clusteringJobsLogic'
import { ClusteringProgress } from './ClusteringProgress'
import { ClusterScatterPlot } from './ClusterScatterPlot'
import { clustersLogic } from './clustersLogic'
import { ClustersTable } from './ClustersTable'
import { toClusterTraceDrawerRow } from './clusterTraceDrawerRow'
import { EvaluationFilterBar } from './EvaluationFilterBar'
import { getJobIdFromRunId } from './types'

export function ClustersView(): JSX.Element {
    const {
        clusteringLevel,
        clusteringRuns,
        clusteringRunsLoading,
        currentRun,
        currentRunLoading,
        filteredSortedClusters,
        effectiveRunId,
        traceSummaries,
        isScatterPlotExpanded,
        propertyFilters,
        shouldFilterTestAccounts,
        propertyFilteredItemIdsLoading,
    } = useValues(clustersLogic)
    const {
        setClusteringLevel,
        setSelectedRunId,
        toggleScatterPlotExpanded,
        setPropertyFilters,
        setShouldFilterTestAccounts,
    } = useActions(clustersLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { jobs } = useValues(clusteringJobsLogic)
    const { config, configLoading } = useValues(clusteringConfigLogic)
    const isLoading = clusteringRunsLoading || currentRunLoading
    const drawerRows = useMemo(
        () =>
            filteredSortedClusters
                .flatMap((cluster) =>
                    Object.entries(cluster.traces)
                        .sort(([, a], [, b]) => a.rank - b.rank)
                        .map(([traceId, traceInfo]) =>
                            toClusterTraceDrawerRow(
                                { traceId, traceInfo, summary: traceSummaries[traceId] },
                                clusteringLevel
                            )
                        )
                )
                .filter((row) => row !== null),
        [filteredSortedClusters, traceSummaries, clusteringLevel]
    )

    return (
        <div className="space-y-4 @container">
            {!configLoading && !config.enabled && (
                <LemonBanner type="info">Clustering is off. Enable it to start new runs for this project.</LemonBanner>
            )}
            <ClusteringProgress compact />
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonSegmentedButton
                        value={clusteringLevel}
                        onChange={setClusteringLevel}
                        options={[
                            { value: 'trace', label: 'Traces' },
                            { value: 'generation', label: 'Generations' },
                            { value: 'evaluation', label: 'Evaluations' },
                        ]}
                        size="small"
                        data-attr="clusters-level-toggle"
                    />
                    <LemonSelect
                        size="small"
                        value={effectiveRunId || undefined}
                        onChange={(value) => setSelectedRunId(value || null)}
                        options={clusteringRuns.map((run) => {
                            const jobId = run.jobId || getJobIdFromRunId(run.runId)
                            const job = jobs.find((job) => String(job.id) === jobId)
                            const jobName =
                                job?.name || run.jobName || (jobId ? `Job ${jobId.slice(0, 8)}` : 'Unassigned run')
                            return { value: run.runId, label: `${jobName} · ${run.label}` }
                        })}
                        placeholder={clusteringRunsLoading ? 'Loading runs…' : 'Select a run'}
                        loading={clusteringRunsLoading}
                        disabledReason={!clusteringRuns.length ? 'No clustering runs yet' : undefined}
                        data-attr="clusters-run-select"
                    />
                    {isLoading && <Spinner className="text-base" captureTime />}
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    <ClusteringEnabledSwitch />
                    <ClusteringJobsButton />
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconScatter />}
                        onClick={toggleScatterPlotExpanded}
                        active={isScatterPlotExpanded}
                        data-attr="clusters-scatter-plot-toggle"
                    >
                        Map
                    </LemonButton>
                </div>
            </div>
            {currentRun && (
                <div className="text-xs text-muted">
                    {currentRun.totalItemsAnalyzed.toLocaleString()}{' '}
                    {clusteringLevel === 'trace'
                        ? 'traces'
                        : clusteringLevel === 'generation'
                          ? 'generations'
                          : 'evaluations'}{' '}
                    analyzed · {dayjs(currentRun.windowStart).format('MMM D')}–
                    {dayjs(currentRun.windowEnd).format('MMM D, YYYY')}
                </div>
            )}
            {clusteringLevel !== 'evaluation' && (
                <div className="flex gap-x-4 gap-y-2 items-center flex-wrap">
                    <PropertyFilters
                        buttonText={clusteringLevel === 'trace' ? 'Filter traces' : 'Filter generations'}
                        propertyFilters={propertyFilters}
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            ...groupsTaxonomicTypes,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.HogQLExpression,
                        ]}
                        onChange={setPropertyFilters}
                        pageKey={`llm-analytics-clusters-${effectiveRunId || 'none'}`}
                    />
                    <Tooltip title="Filter the items shown in this run by their properties. This does not change how clusters are created or affect future runs.">
                        <IconQuestion className="text-muted" />
                    </Tooltip>
                    <div className="flex-1" />
                    {propertyFilteredItemIdsLoading && <Spinner className="text-sm" captureTime />}
                    <TestAccountFilterSwitch
                        checked={shouldFilterTestAccounts}
                        onChange={setShouldFilterTestAccounts}
                    />
                </div>
            )}
            <EvaluationFilterBar />
            {filteredSortedClusters.length > 0 ? (
                <div
                    className={
                        isScatterPlotExpanded
                            ? 'grid grid-cols-1 @[1100px]:grid-cols-[minmax(0,3fr)_minmax(360px,2fr)] gap-4 items-start'
                            : ''
                    }
                >
                    <div className="min-w-0">
                        <ClustersTable />
                    </div>
                    {isScatterPlotExpanded && (
                        <div className="min-w-0 border rounded bg-surface-primary p-3 sticky top-4">
                            <ClusterScatterPlot />
                            <div className="flex justify-between items-center gap-2 text-xs text-muted mt-3">
                                <span>Drag to zoom · Double-click to reset</span>
                                <Tooltip
                                    title="Each dot is an item. Similar items sit near each other. Hover a cluster row to highlight its dots, or click a dot to open its conversation."
                                    docLink="https://posthog.com/docs/ai-observability/clusters"
                                >
                                    <span
                                        className="inline-flex items-center gap-1"
                                        data-attr="clusters-scatter-plot-wth"
                                    >
                                        <IconQuestion /> About this map
                                    </span>
                                </Tooltip>
                            </div>
                        </div>
                    )}
                </div>
            ) : (
                <div className="border rounded p-12 text-center text-muted">
                    {isLoading
                        ? 'Loading clusters…'
                        : currentRun
                          ? 'No clusters match the current filters.'
                          : 'No clustering runs yet. Results will appear here after the first automatic run.'}
                </div>
            )}
            <TraceDrawerRowsSync listId="clusters" rows={drawerRows} />
            <TraceDrawerHost listId="clusters" />
        </div>
    )
}
