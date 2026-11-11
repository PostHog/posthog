import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { evaluationReportPeriodLogic } from '../evaluationReportPeriodLogic'
import { EvaluationResultTrendChart } from '../overview/EvaluationResultTrendChart'
import type { EvaluationReportRun } from '../types'

/** Results over the report's period from live data, so a later backfill shows here and not in the report's numbers. */
export function EvaluationReportPeriodChart({
    evaluationId,
    reportRun,
}: {
    evaluationId: string
    reportRun: EvaluationReportRun
}): JSX.Element | null {
    const logic = evaluationReportPeriodLogic({
        evaluationId,
        runId: reportRun.id,
        periodStart: reportRun.period_start,
        periodEnd: reportRun.period_end,
    })
    const { periodResults, periodResultsLoading, periodResultsFailed, timezone } = useValues(logic)
    const { loadPeriodResults } = useActions(logic)

    if (periodResultsLoading && !periodResults) {
        return <LemonSkeleton className="h-48 w-full" />
    }
    if (periodResultsFailed) {
        return (
            <div className="flex items-center justify-between gap-2 rounded border p-3 text-sm text-secondary">
                <span>Couldn't load the results for this period.</span>
                <LemonButton size="small" type="secondary" onClick={() => loadPeriodResults()}>
                    Try again
                </LemonButton>
            </div>
        )
    }
    const row = periodResults?.row
    // Results older than the event retention come back empty, and an empty chart says nothing the numbers don't.
    if (!periodResults || !row || row.gradedCount === 0) {
        return null
    }
    return (
        <section className="flex flex-col gap-2 rounded border bg-surface-primary p-3">
            <h4 className="mb-0 text-sm font-semibold">Over this period</h4>
            <EvaluationResultTrendChart
                row={row}
                buckets={periodResults.buckets}
                interval={periodResults.interval}
                timezone={timezone}
            />
        </section>
    )
}
