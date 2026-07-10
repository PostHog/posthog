import { BuiltLogic, useValues } from 'kea'

import { LemonTable, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { EvaluationRun } from '../evaluations/types'
import { generationEvaluationRunsLogicType } from '../generationEvaluationRunsLogicType'
import { EvaluationResultTag, getEvaluationResultSortValue } from './EvaluationResultTag'
import { EvaluationRunTargetCell } from './EvaluationRunTargetCell'

export function GenerationEvalRunsTable({
    generationRunsLogic,
}: {
    generationRunsLogic: BuiltLogic<generationEvaluationRunsLogicType>
}): JSX.Element {
    const { generationEvaluationRuns, generationEvaluationRunsLoading } = useValues(generationRunsLogic)

    const columns: LemonTableColumns<EvaluationRun> = [
        {
            title: 'Timestamp',
            key: 'timestamp',
            render: (_, run) => <TZLabel time={run.timestamp} />,
            sorter: (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
        },
        {
            title: 'Evaluation',
            key: 'evaluation',
            render: (_, run) => (
                <Link to={urls.aiObservabilityEvaluation(run.evaluation_id)} className="text-primary font-medium">
                    {run.evaluation_name}
                </Link>
            ),
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
    ]

    return (
        <div>
            <LemonTable
                columns={columns}
                dataSource={generationEvaluationRuns}
                loading={generationEvaluationRunsLoading}
                rowKey="id"
                pagination={{
                    pageSize: 20,
                }}
                emptyState={
                    <div className="text-center py-8">
                        <div className="text-muted mb-2">No evaluations run yet</div>
                        <div className="text-sm text-muted">
                            Evaluation runs for this trace and its generations will appear here.
                        </div>
                    </div>
                }
            />
        </div>
    )
}
