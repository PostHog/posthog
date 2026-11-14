import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCollapse, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { ClusteringJobProgressApi } from '../generated/api.schemas'
import { clusteringConfigLogic } from './clusteringConfigLogic'
import { clusteringProgressLogic } from './clusteringProgressLogic'

function JobProgress({ job }: { job: ClusteringJobProgressApi }): JSX.Element {
    const { retryJob } = useActions(clusteringProgressLogic)
    const { progressLoading } = useValues(clusteringProgressLogic)
    const failed = job.status === 'failed' || job.failure_reason === 'could_not_start'
    const itemLabel = `${job.analysis_level}s`
    const statusLabel = !job.status
        ? 'Not started'
        : failed
          ? 'Could not finish'
          : {
                queued: 'Waiting to start',
                waiting: 'Waiting for data',
                preparing: 'Preparing data',
                clustering: 'Finding clusters',
                completed: job.cluster_count ? 'Finished' : 'No groups found',
                canceled: 'Stopped',
                failed: 'Could not finish',
            }[job.status]
    const needsTracing =
        job.status === 'waiting' && job.eligible_count === 0 && job.analysis_level !== 'evaluation' && !job.has_filters

    return (
        <div className="space-y-2 p-4">
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <strong>{job.name}</strong>
                <LemonTag type={failed ? 'danger' : 'default'}>{statusLabel}</LemonTag>
            </div>
            <div className="text-sm text-muted">
                Needs {job.minimum} {itemLabel}
                {job.analysis_level === 'generation' ? ' from different traces' : ''} in the last {job.lookback_days}{' '}
                days{job.has_filters ? ' that match this job’s filters' : ''}.
                {job.analysis_level === 'evaluation' && ' Numeric and categorical results aren’t included.'}
            </div>
            <div className="text-sm">
                {!job.status || failed ? (
                    <div className="flex justify-between items-center gap-4">
                        <span>
                            {!job.status
                                ? 'Start this job to check its data requirements.'
                                : job.failure_reason === 'preparation_incomplete'
                                  ? 'We couldn’t prepare enough data for this run. Retry this job.'
                                  : 'This job couldn’t finish. Retry to start it again.'}
                        </span>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.AiObservabilityClusters}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => retryJob(job.job_id)}
                                loading={progressLoading}
                            >
                                {job.status ? 'Retry' : 'Start'}
                            </LemonButton>
                        </AccessControlAction>
                    </div>
                ) : job.status === 'waiting' ? (
                    <div className="space-y-2">
                        <div>
                            <strong>
                                {job.eligible_count ?? 0} of {job.minimum}
                            </strong>{' '}
                            found.
                        </div>
                        {needsTracing && (
                            <div>
                                <Link to="https://posthog.com/docs/llm-analytics/installation" target="_blank">
                                    Set up AI tracing
                                </Link>
                            </div>
                        )}
                        {job.analysis_level === 'evaluation' && job.eligible_count === 0 && (
                            <div className="text-muted">
                                This job needs evaluation results. Your trace and generation jobs can run without them.
                            </div>
                        )}
                    </div>
                ) : job.status === 'completed' ? (
                    job.cluster_count ? (
                        `${job.cluster_count} clusters found. Results will appear on this page.`
                    ) : (
                        'There wasn’t enough similarity to form groups. We’ll try again on the next daily run as more data arrives.'
                    )
                ) : job.status === 'preparing' ? (
                    'We’re preparing your data for clustering. You can leave this page; the job will keep running.'
                ) : job.status === 'clustering' ? (
                    'We’re grouping similar items and naming the clusters. Results will appear here.'
                ) : job.status === 'canceled' ? (
                    'This run stopped because clustering or this job was disabled.'
                ) : (
                    'The job is queued. We’ll check for enough data as soon as a worker is available.'
                )}
            </div>
        </div>
    )
}

export function ClusteringProgress({ compact = false }: { compact?: boolean }): JSX.Element | null {
    const { config } = useValues(clusteringConfigLogic)
    const { progress, progressLoading, progressError } = useValues(clusteringProgressLogic)
    const { loadProgress } = useActions(clusteringProgressLogic)
    if (!config.enabled) {
        return null
    }
    if (progressError) {
        return (
            <LemonBanner type="warning" action={{ children: 'Try again', onClick: loadProgress }}>
                We couldn’t load clustering progress.
            </LemonBanner>
        )
    }
    if (!progress.length) {
        return compact ? null : (
            <div role="status" className="p-4">
                {progressLoading ? (
                    <>
                        <Spinner className="mr-2" />
                        Loading your jobs…
                    </>
                ) : (
                    'No jobs are enabled. Open Jobs to choose what to cluster.'
                )}
            </div>
        )
    }
    const visible = compact
        ? progress.filter(
              (job) =>
                  job.status && job.status !== 'canceled' && (job.status !== 'completed' || job.cluster_count === 0)
          )
        : progress
    if (!visible.length) {
        return null
    }
    const rows = (
        <div className="divide-y">
            {visible.map((job) => (
                <JobProgress key={job.job_id} job={job} />
            ))}
            {visible.some((job) => job.status === 'waiting') && (
                <p className="m-0 p-4 text-sm text-muted">
                    We check for new data every 30 minutes. Each job starts automatically once it reaches the required
                    count shown above.
                </p>
            )}
        </div>
    )
    return compact ? (
        <LemonCollapse panels={[{ key: 'progress', header: 'First run progress', content: rows }]} />
    ) : (
        <div className="border rounded bg-surface-primary">{rows}</div>
    )
}
