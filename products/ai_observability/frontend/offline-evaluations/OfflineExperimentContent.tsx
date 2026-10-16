import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonSkeleton, LemonTable, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { OfflineScorerSummaryApi } from '../generated/api.schemas'
import { OfflineExperimentLogicProps, offlineExperimentLogic } from './offlineExperimentLogic'
import { OfflineExperimentStatus } from './OfflineExperimentStatus'
import { OfflineItemInspector } from './OfflineItemInspector'
import { OfflineItemMatrix } from './OfflineItemMatrix'
import { offlineRunSourceLabel } from './offlineOverviewState'
import { offlineScorerHistoryUrl } from './offlineScorerHistoryLogic'
import { OfflineScoreSummaryDisplay } from './OfflineScoreSummaryDisplay'

export function OfflineExperimentContent(props: OfflineExperimentLogicProps): JSX.Element {
    const logic = offlineExperimentLogic(props)
    const {
        experiment,
        experimentLoading,
        experimentError,
        summaries,
        summaryCount,
        summaryCountLoading,
        summariesError,
        inspector,
        cellEpoch,
        completionOpen,
        completionError,
        completedLoading,
    } = useValues(logic)
    const { refresh, showCompletion, hideCompletion, completeOfflineExperiment, openItem, closeItem } =
        useActions(logic)
    const { timezone } = useValues(teamLogic)
    return (
        <div className="flex flex-col gap-4 min-w-0">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonButton to={urls.aiObservabilityOfflineEvaluations()} icon={<IconArrowLeft />}>
                    Experiments
                </LemonButton>
                <LemonButton
                    data-attr="offline-experiment-refresh"
                    type="secondary"
                    icon={<IconRefresh />}
                    loading={experimentLoading}
                    onClick={refresh}
                >
                    Refresh
                </LemonButton>
            </div>
            {experimentError && (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: refresh }}>
                    {experimentError}
                </LemonBanner>
            )}
            {experimentLoading && !experiment ? (
                <LemonSkeleton />
            ) : (
                experiment && (
                    <>
                        <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0">
                                <h2 className="mb-2 break-words">{experiment.name}</h2>
                                <div className="flex flex-wrap items-center gap-2 text-sm">
                                    <OfflineExperimentStatus status={experiment.status} />
                                    <span>{offlineRunSourceLabel(experiment.run_source)}</span>
                                    <TZLabel time={experiment.started_at} />
                                </div>
                            </div>
                            {experiment.status === 'uploading' && (
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Evaluation}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        data-attr="offline-experiment-complete"
                                        type="secondary"
                                        loading={completedLoading}
                                        onClick={showCompletion}
                                    >
                                        Mark as completed
                                    </LemonButton>
                                </AccessControlAction>
                            )}
                        </div>
                        <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
                            <span>{`${experiment.accepted_item_count} items${experiment.expected_item_count === null ? '' : ` / ${experiment.expected_item_count} expected`}`}</span>
                            <span>
                                {experiment.visible_result_count === null
                                    ? 'Score counts unavailable'
                                    : `${experiment.visible_result_count} visible results`}
                            </span>
                            {experiment.expected_result_count !== null && (
                                <span>{`${experiment.expected_result_count} expected results across all scorers`}</span>
                            )}
                        </div>
                        {experiment.status === 'uploading' && (
                            <LemonBanner type="info">
                                This experiment is still receiving uploads. Refresh to see newly accepted items and
                                results.
                            </LemonBanner>
                        )}
                        {completionError && !completionOpen && (
                            <LemonBanner type="error">{completionError}</LemonBanner>
                        )}
                        <details className="rounded border p-3">
                            <summary className="cursor-pointer font-medium">Run details</summary>
                            <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
                                <dt>Experiment ID</dt>
                                <dd className="m-0 font-mono break-all" translate="no">
                                    {experiment.id}
                                </dd>
                                {(
                                    [
                                        'suite_key',
                                        'dataset_source',
                                        'dataset_identifier',
                                        'dataset_revision_identifier',
                                        'application_version',
                                        'model_version',
                                        'prompt_version',
                                    ] as const
                                )
                                    .filter((field) => experiment[field] !== null)
                                    .map((field) => (
                                        <div className="contents" key={field}>
                                            <dt>{field.replaceAll('_', ' ')}</dt>
                                            <dd className="m-0 break-all" translate="no">
                                                {experiment[field]}
                                            </dd>
                                        </div>
                                    ))}
                                <dt>Received</dt>
                                <dd className="m-0">
                                    <TZLabel time={experiment.created_at} />
                                </dd>
                                {experiment.finished_at && (
                                    <>
                                        <dt>Closed</dt>
                                        <dd className="m-0">
                                            <TZLabel time={experiment.finished_at} />
                                        </dd>
                                    </>
                                )}
                            </dl>
                        </details>
                    </>
                )
            )}
            <section>
                {/* Refresh empties the summaries but keeps the last total, so the open prop does not change and React keeps the state the user chose. */}
                <details open={(summaryCount ?? summaries.length) <= 10} className="rounded border p-3">
                    <summary className="cursor-pointer font-medium">{`Scorer summaries${summaries.length ? ` (${summaries.length})` : ''}${summaryCountLoading ? ' · Loading all scorers…' : ''}`}</summary>
                    {summariesError && (
                        <LemonBanner type="error" action={{ children: 'Try again', onClick: refresh }}>
                            {summariesError}
                        </LemonBanner>
                    )}
                    <LemonTable
                        className="mt-3"
                        tableLayout="fixed"
                        dataSource={summaries}
                        loading={summaryCountLoading && !summaries.length}
                        rowKey={(summary) => summary.scorer.id}
                        size="small"
                        emptyState={
                            summariesError
                                ? 'Scorer summaries are unavailable.'
                                : 'No results have been submitted for visible scorers.'
                        }
                        columns={[
                            {
                                title: 'Scorer',
                                render: (_, summary: OfflineScorerSummaryApi) => (
                                    <Link
                                        className="break-words"
                                        to={offlineScorerHistoryUrl(summary.scorer, experiment, timezone)}
                                    >{`${summary.scorer.name} v${summary.scorer.version}`}</Link>
                                ),
                            },
                            {
                                title: 'Summary',
                                render: (_, summary: OfflineScorerSummaryApi) => (
                                    <OfflineScoreSummaryDisplay summary={summary} />
                                ),
                            },
                            {
                                title: 'Coverage',
                                render: (_, summary: OfflineScorerSummaryApi) => (
                                    <details>
                                        <summary className="cursor-pointer text-xs">{`${summary.status_counts.ok} scored · ${summary.status_counts.error} errors · ${summary.missing_result_count} missing`}</summary>
                                        <p className="text-xs mb-0">{`${summary.status_counts.skipped} skipped · ${summary.status_counts.not_applicable} not applicable · ${summary.distinct_case_count} distinct cases · ${summary.trial_item_count} trial items · ${summary.distinct_trial_count} distinct trials · ${summary.items_without_case_key_count} items without a case key`}</p>
                                        {summary.scorer.kind === 'boolean' && (
                                            <p className="text-xs mb-0">{`${summary.true_count} true · ${summary.false_count} false`}</p>
                                        )}
                                    </details>
                                ),
                            },
                        ]}
                    />
                </details>
            </section>
            <OfflineItemMatrix {...props} />
            {inspector && (
                <OfflineItemInspector
                    key={`${inspector.itemId}:${cellEpoch}`}
                    {...props}
                    {...inspector}
                    onClose={closeItem}
                    onSelectResult={(result) => openItem(result.item_id, result.id, result.scorer.id)}
                />
            )}
            <LemonModal
                isOpen={completionOpen}
                onClose={hideCompletion}
                title="Mark experiment as completed?"
                footer={
                    <>
                        <LemonButton type="secondary" onClick={hideCompletion} disabled={completedLoading}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            data-attr="offline-experiment-confirm-complete"
                            type="primary"
                            loading={completedLoading}
                            onClick={() => completeOfflineExperiment()}
                        >
                            Mark as completed
                        </LemonButton>
                    </>
                }
            >
                <p>
                    This closes the experiment to new results. Accepted results are preserved, and identical upload
                    retries remain safe.
                </p>
                {experiment?.expected_item_count === null && experiment.expected_result_count === null && (
                    <p>
                        No expected counts were declared. Completion records your decision that uploading is finished.
                    </p>
                )}
                {completionError && <LemonBanner type="error">{completionError}</LemonBanner>}
            </LemonModal>
        </div>
    )
}
