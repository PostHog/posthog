import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconArrowLeft } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect, LemonSkeleton, LemonSwitch, LemonTable, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import type { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { ScorerLabel } from '../scoreDefinitions/ScorerLabel'
import { comparisonScoreRows, comparisonUrl, type ComparisonScoreRow } from './offlineComparison'
import { offlineComparisonLogic, type OfflineComparisonProps } from './offlineComparisonLogic'
import { OfflineComparisonScoreCell } from './OfflineComparisonScoreCell'
import { OfflineExperimentStatus } from './OfflineExperimentStatus'
import { OFFLINE_ALL_UPLOAD_STATES } from './offlineOverviewState'
import { offlineScoreMetricLabel } from './offlineScoreTrends'

type ComparisonRow = { kind: 'coverage'; id: string } | { kind: 'dataset'; id: string } | ComparisonScoreRow

export function OfflineExperimentComparison(props: OfflineComparisonProps): JSX.Element {
    const { experimentIds } = props
    const { runs, runsLoading, error } = useValues(offlineComparisonLogic(props))
    const { loadComparison } = useActions(offlineComparisonLogic(props))
    const { searchParams } = useValues(router)
    const baselineId = experimentIds[0]
    const orderedRuns = [...(runs ?? [])].sort(
        (a, b) => experimentIds.indexOf(a.experiment.id) - experimentIds.indexOf(b.experiment.id)
    )
    const scores = comparisonScoreRows(orderedRuns)
    const shared = scores.filter((row) => row.scores.size === orderedRuns.length)
    const sharedOnly = searchParams.compare_scores === 'shared' && shared.length > 0
    const rows: ComparisonRow[] = [
        { kind: 'coverage', id: 'coverage' },
        { kind: 'dataset', id: 'dataset' },
        ...(sharedOnly ? shared : scores),
    ]
    const columns: LemonTableColumns<ComparisonRow> = [
        {
            title: 'Measure',
            key: 'measure',
            className: 'min-w-32 align-top',
            render: (_, row) => {
                if (row.kind === 'item' || row.kind === 'experiment') {
                    return (
                        <div className="flex flex-col items-start gap-0.5">
                            <Link
                                to={
                                    combineUrl(urls.aiObservabilityOfflineScorerHistory(row.scorer.definition_id), {
                                        version: row.id,
                                        date_from: 'all',
                                        statuses: OFFLINE_ALL_UPLOAD_STATES,
                                        tags: [],
                                    }).url
                                }
                                target="_blank"
                                targetBlankIcon
                                className="inline-flex max-w-full items-center gap-0.5 font-semibold"
                                data-attr="offline-comparison-open-scorer"
                            >
                                <ScorerLabel scorer={row.scorer} />
                            </Link>
                            <span className="text-xs text-muted">
                                {row.kind === 'experiment' ? 'Experiment score' : offlineScoreMetricLabel(row.scorer)}
                            </span>
                        </div>
                    )
                }
                return row.kind === 'coverage' ? 'Items' : 'Dataset'
            },
        },
        ...orderedRuns.map((run): LemonTableColumns<ComparisonRow>[number] => {
            const { experiment } = run
            return {
                key: experiment.id,
                className: 'align-top',
                title: (
                    <div className="min-w-40 max-w-72 space-y-0.5 normal-case tracking-normal whitespace-normal">
                        <Link
                            to={urls.aiObservabilityOfflineEvaluationExperiment(experiment.id)}
                            target="_blank"
                            targetBlankIcon
                            data-attr="offline-comparison-open-experiment"
                            className="break-words font-semibold text-sm"
                        >
                            {experiment.name}
                        </Link>
                        <div className="text-xs text-muted font-normal">
                            {experiment.id === baselineId && 'Baseline · '}
                            <TZLabel time={experiment.started_at} />
                        </div>
                    </div>
                ),
                render: (_, row) => {
                    if (row.kind === 'coverage') {
                        return (
                            <div className="flex flex-wrap items-center gap-2">
                                <strong className="tabular-nums">
                                    {experiment.accepted_item_count.toLocaleString()}
                                </strong>
                                <OfflineExperimentStatus status={experiment.status} />
                            </div>
                        )
                    }
                    if (row.kind === 'dataset') {
                        return (
                            <div className="max-w-72 break-words">
                                {[experiment.dataset_source, experiment.dataset_identifier]
                                    .filter(Boolean)
                                    .join(' / ') || 'Unspecified'}
                                {(experiment.dataset_revision_identifier || experiment.dataset_revision_id) && (
                                    <div className="text-xs text-muted">
                                        Revision{' '}
                                        {experiment.dataset_revision_identifier || experiment.dataset_revision_id}
                                    </div>
                                )}
                            </div>
                        )
                    }
                    return <OfflineComparisonScoreCell row={row} run={run} baselineId={baselineId} />
                },
            }
        }),
    ]
    return (
        <section aria-label="Experiment comparison" className="min-w-0 space-y-3">
            <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={comparisonUrl([], searchParams)}>
                Back to experiments
            </LemonButton>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="mb-0">Compare experiments</h2>
                {orderedRuns.length > 1 && (
                    <LemonSelect
                        size="small"
                        aria-label="Baseline experiment"
                        data-attr="offline-comparison-baseline"
                        value={baselineId}
                        options={orderedRuns.map(({ experiment }) => ({
                            value: experiment.id,
                            label: experiment.name,
                            labelInMenu: (
                                <>
                                    {experiment.name} · <TZLabel time={experiment.started_at} />
                                </>
                            ),
                        }))}
                        onChange={(id) =>
                            router.actions.push(
                                comparisonUrl([id, ...experimentIds.filter((other) => other !== id)], searchParams)
                            )
                        }
                        renderButtonContent={(option) => (
                            <span className="block max-w-52 truncate">Baseline · {option?.label}</span>
                        )}
                    />
                )}
            </div>
            {!experimentIds.length ? (
                <LemonBanner type="warning">Select two to four experiments from the list to compare them.</LemonBanner>
            ) : error ? (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadComparison() }}>
                    {error}
                </LemonBanner>
            ) : !runs || runsLoading ? (
                <LemonSkeleton className="h-48" />
            ) : (
                <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-muted mb-0">
                            Each run can contain different items. Score changes are relative to the selected baseline.
                        </p>
                        {shared.length > 0 && shared.length < scores.length && (
                            <LemonSwitch
                                size="small"
                                label="Shared scores only"
                                data-attr="offline-comparison-shared-scores"
                                checked={sharedOnly}
                                onChange={(checked) =>
                                    router.actions.replace(
                                        comparisonUrl(experimentIds, {
                                            ...searchParams,
                                            compare_scores: checked ? 'shared' : undefined,
                                        })
                                    )
                                }
                            />
                        )}
                    </div>
                    {scores.length > 0 && shared.length === 0 && (
                        <LemonBanner type="info">
                            No visible scorer version appears in every experiment. Each run’s scores are shown below.
                        </LemonBanner>
                    )}
                    <LemonTable columns={columns} dataSource={rows} rowKey="id" firstColumnSticky size="small" />
                    {!scores.length && (
                        <LemonBanner type="info">
                            These experiments have no visible scores. Open an experiment to inspect its items.
                        </LemonBanner>
                    )}
                </>
            )}
        </section>
    )
}
