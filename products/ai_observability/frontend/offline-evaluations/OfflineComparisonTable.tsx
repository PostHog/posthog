import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { LemonBanner, LemonSwitch, LemonTable, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import type { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { urls } from 'scenes/urls'

import { ScorerLabel } from '../scoreDefinitions/ScorerLabel'
import { comparisonScoreRows, comparisonUrl, type ComparisonRun, type ComparisonScoreRow } from './offlineComparison'
import { OfflineComparisonScoreCell } from './OfflineComparisonScoreCell'
import { OfflineExperimentStatus } from './OfflineExperimentStatus'
import { OFFLINE_ALL_UPLOAD_STATES } from './offlineOverviewState'
import { offlineScoreMetricLabel } from './offlineScoreTrends'

type ComparisonRow = { kind: 'coverage'; id: string } | { kind: 'dataset'; id: string } | ComparisonScoreRow

export function OfflineComparisonTable({
    orderedRuns,
    experimentIds,
    canOpenDatasets,
}: {
    orderedRuns: ComparisonRun[]
    experimentIds: string[]
    canOpenDatasets: boolean
}): JSX.Element {
    const { searchParams } = useValues(router)
    const baselineId = experimentIds[0]
    const scores = comparisonScoreRows(orderedRuns)
    const shared = scores.filter((row) => row.scores.size === experimentIds.length)
    const sharedOnly = searchParams.compare_scores === 'shared' && shared.length > 0
    const pagination = usePagination(sharedOnly ? shared : scores, {
        pageSize: 20,
        useUrl: false,
        showPageSelector: true,
    })
    const rows: ComparisonRow[] = [
        { kind: 'coverage', id: 'coverage' },
        { kind: 'dataset', id: 'dataset' },
        ...pagination.dataSourcePage,
    ]
    const columns: LemonTableColumns<ComparisonRow> = [
        {
            title: 'Measure',
            key: 'measure',
            className: 'min-w-32 align-top',
            render: (_, row) => {
                if (row.kind === 'item' || row.kind === 'experiment') {
                    return (
                        <div className="flex flex-col items-start gap-0.5 font-semibold">
                            <ScorerLabel
                                scorer={row.scorer}
                                historyLink={{
                                    to: combineUrl(urls.aiObservabilityOfflineScorerHistory(row.scorer.definition_id), {
                                        version: row.id,
                                        date_from: 'all',
                                        statuses: OFFLINE_ALL_UPLOAD_STATES,
                                        tags: [],
                                    }).url,
                                    'data-attr': 'offline-comparison-open-scorer',
                                }}
                            />
                            <span className="text-xs font-normal text-muted">
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
                            {experiment.id === baselineId && <span>Baseline · </span>}
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
                        const datasetLabel =
                            [experiment.dataset_source, experiment.dataset_identifier].filter(Boolean).join(' / ') ||
                            'Unspecified'
                        const datasetUrl =
                            canOpenDatasets &&
                            experiment.dataset_source === 'posthog' &&
                            experiment.dataset_revision_id &&
                            experiment.dataset_identifier
                                ? urls.aiObservabilityDataset(experiment.dataset_identifier)
                                : null
                        return (
                            <div className="max-w-72 break-words">
                                {datasetUrl ? (
                                    <Link
                                        to={datasetUrl}
                                        target="_blank"
                                        targetBlankIcon
                                        data-attr="offline-comparison-open-dataset"
                                    >
                                        {datasetLabel}
                                    </Link>
                                ) : (
                                    datasetLabel
                                )}
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
            {scores.length > 0 && shared.length === 0 && orderedRuns.length === experimentIds.length && (
                <LemonBanner type="info">
                    No visible scorer version appears in every experiment. Each run’s scores are shown below.
                </LemonBanner>
            )}
            <LemonTable
                columns={columns}
                dataSource={rows}
                rowKey="id"
                rowClassName={(row) => (row.kind === 'experiment' ? '[&>td]:align-middle' : null)}
                firstColumnSticky
                size="small"
            />
            <PaginationControl {...pagination} nouns={['score', 'scores']} />
            {!scores.length && (
                <LemonBanner type="info">
                    These experiments have no visible scores. Open an experiment to inspect its items.
                </LemonBanner>
            )}
        </>
    )
}
