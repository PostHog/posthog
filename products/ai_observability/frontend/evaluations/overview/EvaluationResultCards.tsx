import { cn } from 'lib/utils/css-classes'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { EvaluationCategoryShares } from './EvaluationCategoryShares'
import { EvaluationFailingExamples } from './EvaluationFailingExamples'
import type { BucketInterval } from './evaluationOverviewDisplay'
import { EvaluationResultDetails } from './EvaluationResultDetails'
import type { DetailsLoad } from './evaluationResultDrawerLogic'
import { EvaluationResultOutcomes } from './EvaluationResultOutcomes'
import { EvaluationResultTrendChart, type TrendBreakdownSeries } from './EvaluationResultTrendChart'
import { EvaluationScoreHistogram } from './EvaluationScoreHistogram'

function Card({
    title,
    action,
    className,
    children,
}: {
    title: string
    action?: React.ReactNode
    className?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className={cn('border rounded bg-surface-primary p-3 flex flex-col gap-2 min-w-0', className)}>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="mb-0 text-sm font-semibold">{title}</h4>
                {action}
            </div>
            {children}
        </section>
    )
}

export function EvaluationResultCards({
    row,
    buckets,
    interval,
    timezone,
    details,
    onRetryDetails,
    onSelectBucket,
    chartFooter,
    chartAction,
    breakdown,
    showFailingExamples = true,
}: {
    row: EvaluationResultApi
    buckets: string[]
    interval: BucketInterval
    timezone: string
    details: DetailsLoad | null
    onRetryDetails: () => void
    onSelectBucket?: (bucket: string) => void
    chartFooter?: React.ReactNode
    chartAction?: React.ReactNode
    breakdown?: TrendBreakdownSeries[] | null
    /** The evaluation page lists every run below the cards, failing ones a filter away, so it leaves them out. */
    showFailingExamples?: boolean
}): JSX.Element {
    const { summary } = row
    const hasScore = summary.kind === 'score' || (summary.kind === 'pass_rate' && row.outputType === 'numeric')
    // Outcomes alone on its row takes the full width rather than leaving half of it empty.
    const outcomesAlone = !hasScore && !showFailingExamples

    return (
        <div className="@container">
            <div className="grid gap-3 grid-cols-1 @2xl:grid-cols-2 items-start">
                <Card title="Over time" action={chartAction} className="@2xl:col-span-2">
                    <EvaluationResultTrendChart
                        row={row}
                        buckets={buckets}
                        interval={interval}
                        timezone={timezone}
                        onSelectBucket={onSelectBucket}
                        footer={chartFooter}
                        breakdown={breakdown}
                    />
                </Card>
                {summary.kind === 'pass_rate' && (
                    <Card title="Outcomes" className={outcomesAlone ? '@2xl:col-span-2' : undefined}>
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
                        <EvaluationResultDetails load={details} onRetry={onRetryDetails}>
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
                {summary.kind === 'pass_rate' && showFailingExamples && (
                    <Card title="Recent failing examples">
                        <EvaluationResultDetails load={details} onRetry={onRetryDetails}>
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
