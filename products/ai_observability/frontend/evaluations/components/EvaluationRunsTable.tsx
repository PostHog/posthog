import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSegmentedButton, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { EvaluationResultTag, getEvaluationResultSortValue } from '../../components/EvaluationResultTag'
import { EvaluationRunTargetCell } from '../../components/EvaluationRunTargetCell'
import { evaluationSupportsRunOutcomes } from '../evaluationCapabilities'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationRun, SentimentEvaluationRunsFilter } from '../types'
import { EvaluationRunsFilters } from './EvaluationRunsFilters'

const SENTIMENT_FILTER_OPTIONS: { value: SentimentEvaluationRunsFilter; label: string }[] = [
    { value: 'negative', label: 'Negative' },
    { value: 'positive', label: 'Positive' },
    { value: 'neutral', label: 'Neutral' },
    { value: 'all', label: 'All' },
]

function SentimentEvaluationRunsFilters(): JSX.Element {
    const { evaluationRunsFilter } = useValues(llmEvaluationLogic)
    const { setEvaluationRunsFilter } = useActions(llmEvaluationLogic)

    return (
        <LemonSegmentedButton
            value={evaluationRunsFilter as SentimentEvaluationRunsFilter}
            onChange={(value) => {
                setEvaluationRunsFilter(value as SentimentEvaluationRunsFilter, evaluationRunsFilter)
            }}
            options={SENTIMENT_FILTER_OPTIONS}
            size="small"
            data-attr="llma-sentiment-evaluation-runs-filter"
        />
    )
}

export function EvaluationRunsTable(): JSX.Element {
    const { filteredEvaluationRuns, evaluationRuns, evaluationRunsError, evaluation, evaluationRunsLoading } =
        useValues(llmEvaluationLogic)
    const { refreshEvaluationRuns } = useActions(llmEvaluationLogic)
    const showOutcomeFilters = evaluationSupportsRunOutcomes(evaluation)
    const showSentimentFilters = evaluation?.evaluation_type === 'sentiment'

    // A filter is hiding rows when the evaluation has runs but none match the current filter.
    const filterHidesRuns = evaluationRuns.length > 0 && filteredEvaluationRuns.length === 0
    // LemonTable drops its empty state as soon as it has rows, so a failed refresh over rows that
    // are already on screen needs its own surface. Without it the spinner just stops and the user
    // reads the stale rows as current.
    const showStaleRunsBanner = evaluationRunsError && filteredEvaluationRuns.length > 0

    const emptyState = evaluationRunsError ? (
        <div className="text-center py-8">
            <div className="text-muted mb-2">Could not load evaluation runs</div>
            <div className="text-sm text-muted mb-3">The query failed. This is usually temporary. Try again.</div>
            <LemonButton
                type="secondary"
                icon={<IconRefresh />}
                onClick={refreshEvaluationRuns}
                loading={evaluationRunsLoading}
                size="small"
                data-attr="llma-evaluation-runs-retry"
            >
                Retry
            </LemonButton>
        </div>
    ) : filterHidesRuns ? (
        <div className="text-center py-8">
            <div className="text-muted mb-2">No runs match this filter</div>
            <div className="text-sm text-muted">Change the filter above to see this evaluation's other runs.</div>
        </div>
    ) : (
        <div className="text-center py-8">
            <div className="text-muted mb-2">No evaluation runs yet</div>
            <div className="text-sm text-muted">
                Runs will appear here once this evaluation starts executing based on your triggers.
            </div>
        </div>
    )

    const columns: LemonTableColumns<EvaluationRun> = [
        {
            title: 'Timestamp',
            key: 'timestamp',
            render: (_, run) => <TZLabel time={run.timestamp} />,
            sorter: (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
        },
        {
            title: 'Target',
            key: 'target',
            render: (_, run) => <EvaluationRunTargetCell run={run} />,
        },
        {
            title: 'Result',
            key: 'result',
            render: (_, run) => <EvaluationResultTag run={run} />,
            sorter: (a, b) => {
                return getEvaluationResultSortValue(b) - getEvaluationResultSortValue(a)
            },
        },
        {
            title: 'Reasoning',
            key: 'reasoning',
            render: (_, run) => (
                <Tooltip title={run.reasoning}>
                    <div className="max-w-md cursor-default">
                        <div className="text-sm text-default line-clamp-2">{run.reasoning}</div>
                    </div>
                </Tooltip>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, run) => {
                const statusMap = {
                    completed: { type: 'success' as const, text: 'Completed' },
                    failed: { type: 'danger' as const, text: 'Failed' },
                    running: { type: 'primary' as const, text: 'Running' },
                }
                const status = statusMap[run.status]
                return <LemonTag type={status.type}>{status.text}</LemonTag>
            },
        },
    ]

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                {showOutcomeFilters ? (
                    <EvaluationRunsFilters />
                ) : showSentimentFilters ? (
                    <SentimentEvaluationRunsFilters />
                ) : (
                    <div />
                )}
                <LemonButton
                    type="secondary"
                    icon={<IconRefresh />}
                    onClick={refreshEvaluationRuns}
                    loading={evaluationRunsLoading}
                    size="small"
                    data-attr="llma-evaluation-refresh-runs"
                >
                    Refresh
                </LemonButton>
            </div>

            {showStaleRunsBanner && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: refreshEvaluationRuns,
                        'data-attr': 'llma-evaluation-runs-stale-retry',
                    }}
                >
                    We couldn't refresh the evaluation runs. The runs below may be out of date.
                </LemonBanner>
            )}

            <LemonTable
                columns={columns}
                dataSource={filteredEvaluationRuns}
                loading={evaluationRunsLoading}
                rowKey="id"
                pagination={{
                    pageSize: 50,
                }}
                emptyState={emptyState}
            />
        </div>
    )
}
