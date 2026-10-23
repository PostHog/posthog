import { useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { EvaluationCategoryShares } from './EvaluationCategoryShares'
import { EvaluationDrawerEmptyState } from './EvaluationDrawerEmptyState'
import { EvaluationFailingExamples } from './EvaluationFailingExamples'
import { describeAttention } from './evaluationOverviewDisplay'
import { EvaluationPausedNotice } from './EvaluationPausedNotice'
import { EvaluationResultDetails } from './EvaluationResultDetails'
import { evaluationResultDrawerLogic } from './evaluationResultDrawerLogic'
import { EvaluationResultOutcomes } from './EvaluationResultOutcomes'
import { EvaluationResultTrendChart } from './EvaluationResultTrendChart'
import { EvaluationScoreHistogram } from './EvaluationScoreHistogram'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

function Card({
    title,
    className,
    children,
}: {
    title: string
    className?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className={cn('border rounded bg-surface-primary p-3 flex flex-col gap-2 min-w-0', className)}>
            <h4 className="mb-0 text-sm font-semibold">{title}</h4>
            {children}
        </section>
    )
}

export function EvaluationResultExpanded({ row }: { row: EvaluationResultApi }): JSX.Element {
    const { configById, timezone, evaluationUrl } = useValues(evaluationsOverviewLogic)
    const { openDetails } = useValues(evaluationResultDrawerLogic)
    const { summary } = row
    const errored = row.attentionReasons.includes('errored')
    const enabled = configById.get(row.id)?.enabled ?? row.enabled
    const hasScore = summary.kind === 'score' || (summary.kind === 'pass_rate' && row.outputType === 'numeric')

    const notice = errored ? (
        <LemonBanner type="error">
            <span>{`${describeAttention(row, timezone)}. `}</span>
            <Link to={evaluationUrl(row.id)}>Open the evaluation to fix it.</Link>
        </LemonBanner>
    ) : !enabled ? (
        <EvaluationPausedNotice row={row} />
    ) : null

    if (row.gradedCount === 0) {
        return <EvaluationDrawerEmptyState row={row} />
    }

    return (
        <div className="@container flex flex-col gap-3">
            {notice}
            <div className="grid gap-3 grid-cols-1 @2xl:grid-cols-2">
                <Card title="Over time" className="@2xl:col-span-2">
                    <EvaluationResultTrendChart row={row} />
                </Card>
                {summary.kind === 'pass_rate' && (
                    <Card title="Outcomes">
                        <EvaluationResultOutcomes row={row} summary={summary} />
                    </Card>
                )}
                {(summary.kind === 'categories' || summary.kind === 'sentiment') && (
                    <Card title={summary.kind === 'sentiment' ? 'Sentiment split' : 'Labels'}>
                        <EvaluationCategoryShares summary={summary} gradedCount={row.gradedCount} />
                    </Card>
                )}
                {hasScore && (
                    <Card title="Score distribution">
                        <EvaluationResultDetails evaluationId={row.id} load={openDetails}>
                            {(details) =>
                                details.scoreDistribution ? (
                                    <EvaluationScoreHistogram histogram={details.scoreDistribution} />
                                ) : (
                                    <div className="text-sm text-secondary">
                                        Set score bounds on the evaluation to see how scores spread.
                                    </div>
                                )
                            }
                        </EvaluationResultDetails>
                    </Card>
                )}
                {summary.kind === 'pass_rate' && (
                    <Card title="Recent failing examples">
                        <EvaluationResultDetails evaluationId={row.id} load={openDetails}>
                            {(details) =>
                                details.recentFailures && details.recentFailures.length > 0 ? (
                                    <EvaluationFailingExamples failures={details.recentFailures} />
                                ) : (
                                    <div className="text-sm text-secondary">No failed runs in this range.</div>
                                )
                            }
                        </EvaluationResultDetails>
                    </Card>
                )}
            </div>
        </div>
    )
}
