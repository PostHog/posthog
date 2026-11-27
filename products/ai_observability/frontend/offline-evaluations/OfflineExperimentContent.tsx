import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { OfflineScorerSummaryApi } from '../generated/api.schemas'
import { TraceDrawerHost } from '../redesign/trace/TraceDrawerHost'
import { ScorerLabel } from '../scoreDefinitions/ScorerLabel'
import { ExperimentScoreResult } from './ExperimentScoreResult'
import { OfflineExperimentLogicProps, offlineExperimentLogic } from './offlineExperimentLogic'
import { OfflineExperimentStatus } from './OfflineExperimentStatus'
import { OfflineItemInspector } from './OfflineItemInspector'
import { OfflineItemMatrix } from './OfflineItemMatrix'
import { offlineRunSourceLabel } from './offlineOverviewState'
import { OfflineRunDetails } from './OfflineRunDetails'
import { offlineScorerHistoryUrl } from './offlineScorerHistoryLogic'
import { OfflineScoreSummaryDisplay } from './OfflineScoreSummaryDisplay'
import { offlineUnscoredLabel } from './offlineUnscoredLabel'

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
                <LemonButton
                    to={urls.aiObservabilityOfflineEvaluations()}
                    icon={<IconArrowLeft />}
                    data-attr="offline-experiment-back"
                >
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
                        {experiment.status === 'uploading' && (
                            <LemonBanner type="info">
                                This experiment is still receiving uploads. Refresh to see newly accepted items and
                                results.
                            </LemonBanner>
                        )}
                        {completionError && !completionOpen && (
                            <LemonBanner type="error">{completionError}</LemonBanner>
                        )}
                    </>
                )
            )}
            <section aria-label="Scores" className="min-w-0 rounded-lg border bg-surface-primary">
                {experiment?.experiment_score && (
                    <ExperimentScoreResult
                        score={experiment.experiment_score}
                        itemSummaries={summaries}
                        historyUrl={offlineScorerHistoryUrl(
                            {
                                id: experiment.experiment_score.scorer_version_id,
                                definition_id: experiment.experiment_score.definition_id,
                            },
                            experiment,
                            timezone
                        )}
                    />
                )}
                {/* Refresh empties the summaries but keeps the last total, so the open prop does not change and React keeps the state the user chose. */}
                <details open={(summaryCount ?? summaries.length) <= 10} className="px-4 py-3">
                    <summary
                        className="cursor-pointer font-medium"
                        data-attr="offline-experiment-item-scores"
                    >{`Item scores${summaries.length ? ` (${summaries.length})` : ''}${summaryCountLoading ? ' · Loading all scorers…' : ''}`}</summary>
                    {summariesError && (
                        <LemonBanner type="error" action={{ children: 'Try again', onClick: refresh }}>
                            {summariesError}
                        </LemonBanner>
                    )}
                    <LemonTable
                        className="mt-3 [&_tbody_td]:align-top"
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
                                    <ScorerLabel
                                        scorer={summary.scorer}
                                        historyLink={{
                                            to: offlineScorerHistoryUrl(summary.scorer, experiment, timezone),
                                            'data-attr': 'offline-experiment-scorer-history',
                                        }}
                                    />
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
                                        <summary
                                            className="cursor-pointer text-xs"
                                            data-attr="offline-experiment-scorer-coverage"
                                        >{`${summary.status_counts.ok} scored · ${summary.status_counts.error} errors · ${offlineUnscoredLabel(summary)}`}</summary>
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
                {experiment && !experiment.experiment_score && (
                    <div className="flex border-t px-4 py-2">
                        {experiment.suite_has_score ? (
                            <span className="py-1 text-sm text-muted">
                                Future runs of {experiment.suite_key} have an experiment score.
                            </span>
                        ) : (
                            <AccessControlAction
                                resourceType={AccessControlResourceType.LlmAnalytics}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                <LemonButton
                                    size="small"
                                    type="tertiary"
                                    data-attr="aio-set-up-experiment-score"
                                    tooltipPlacement="top-start"
                                    tooltip="Preview a formula using this run’s item scores, then save it for future runs."
                                    to={`${urls.aiObservabilityScorer('new')}?${new URLSearchParams({ experiment: experiment.id, ...(experiment.suite_key ? { suite: experiment.suite_key } : {}) })}`}
                                >
                                    {experiment.suite_key ? 'Set up experiment score' : 'Create experiment scorer'}
                                </LemonButton>
                            </AccessControlAction>
                        )}
                    </div>
                )}
            </section>
            {experiment && <OfflineRunDetails experiment={experiment} />}
            <OfflineItemMatrix {...props} />
            <TraceDrawerHost listId="offline-experiment" />
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
                        <LemonButton
                            type="secondary"
                            onClick={hideCompletion}
                            disabled={completedLoading}
                            data-attr="offline-experiment-cancel-complete"
                        >
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
