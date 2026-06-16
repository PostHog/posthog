import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { EvaluationResultTag, getEvaluationResultSortValue } from '../../components/EvaluationResultTag'
import { sanitizeTraceUrlSearchParams } from '../../utils'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationRun } from '../types'
import { EvaluationSummaryControls, EvaluationSummaryPanel } from './EvaluationSummaryPanel'

export function EvaluationRunsTable(): JSX.Element {
    const { filteredEvaluationRuns, evaluationRunsLoading, runsLookup } = useValues(llmEvaluationLogic)
    const { searchParams } = useValues(router)
    const traceSearchParams = sanitizeTraceUrlSearchParams(searchParams, { removeSearch: true })
    const { refreshEvaluationRuns } = useActions(llmEvaluationLogic)

    const columns: LemonTableColumns<EvaluationRun> = [
        {
            title: 'Timestamp',
            key: 'timestamp',
            render: (_, run) => <TZLabel time={run.timestamp} />,
            sorter: (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
        },
        {
            title: 'Generation ID',
            key: 'generation_id',
            render: (_, run) => {
                if (!run.generation_id) {
                    return <span className="font-mono text-sm text-muted">—</span>
                }
                return (
                    <div className="font-mono text-sm">
                        <Link
                            to={
                                combineUrl(urls.aiObservabilityTrace(run.trace_id), {
                                    ...traceSearchParams,
                                    event: run.generation_id,
                                }).url
                            }
                            className="text-primary"
                        >
                            {run.generation_id.slice(0, 12)}...
                        </Link>
                    </div>
                )
            },
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
                <EvaluationSummaryControls />
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

            <EvaluationSummaryPanel runsLookup={runsLookup} />

            <LemonTable
                columns={columns}
                dataSource={filteredEvaluationRuns}
                loading={evaluationRunsLoading}
                rowKey="id"
                pagination={{
                    pageSize: 50,
                }}
                emptyState={
                    <div className="text-center py-8">
                        <div className="text-muted mb-2">No evaluation runs yet</div>
                        <div className="text-sm text-muted">
                            Runs will appear here once this evaluation starts executing based on your triggers.
                        </div>
                    </div>
                }
            />
        </div>
    )
}
