import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonSkeleton, LemonTag, LemonTagProps, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import { TraceViewMode, aiObservabilityTraceLogic } from '../aiObservabilityTraceLogic'
import { EvaluationRun } from '../evaluations/types'
import { generationEvaluationRunsLogic } from '../generationEvaluationRunsLogic'
import { getEvaluationResultDisplay } from './EvaluationResultTag'

export interface EvalSummary {
    latestRun: EvaluationRun
    runCount: number
}

export function getEvalSummaries(runs: EvaluationRun[]): EvalSummary[] {
    const sorted = [...runs].sort((a, b) => dayjs(b.timestamp).valueOf() - dayjs(a.timestamp).valueOf())
    const byEvalId = new Map<string, EvalSummary>()
    for (const run of sorted) {
        const existing = byEvalId.get(run.evaluation_id)
        if (existing) {
            existing.runCount++
        } else {
            byEvalId.set(run.evaluation_id, { latestRun: run, runCount: 1 })
        }
    }
    return Array.from(byEvalId.values())
}

export function getEvalBadgeProps(run: EvaluationRun): {
    type: LemonTagProps['type']
    icon: JSX.Element
    label: string
} {
    const { type, icon, label } = getEvaluationResultDisplay(run)
    return { type, icon, label }
}

function EvalTooltipContent({ latestRun, runCount }: EvalSummary): JSX.Element {
    return (
        <div className="max-w-80 space-y-1">
            <div className="font-semibold">{latestRun.evaluation_name}</div>
            <div className="text-xs opacity-75">
                {dayjs(latestRun.timestamp).fromNow()}
                {runCount > 1 && <> &middot; {pluralize(runCount, 'run', 'runs', true)} total</>}
            </div>
            {latestRun.reasoning && <div className="text-sm">{latestRun.reasoning}</div>}
        </div>
    )
}

export function EvalResultBadges({
    traceId,
    generationEventId,
}: {
    traceId: string
    /** When set, show runs targeting this generation; otherwise show trace-target runs. */
    generationEventId?: string
}): JSX.Element | null {
    const { generationEvaluationRuns, generationEvaluationRunsLoading } = useValues(
        generationEvaluationRunsLogic({ lookupBy: 'trace', traceId })
    )
    const traceLogic = useMountedLogic(aiObservabilityTraceLogic)
    const { setViewMode } = useActions(traceLogic)

    if (generationEvaluationRunsLoading && generationEvaluationRuns.length === 0) {
        return (
            <div className="flex flex-row items-center gap-1.5">
                <LemonSkeleton className="h-5 w-24" />
                <LemonSkeleton className="h-5 w-24" />
            </div>
        )
    }

    const scopedRuns = generationEventId
        ? generationEvaluationRuns.filter((run) => run.generation_id === generationEventId)
        : generationEvaluationRuns.filter((run) => !run.generation_id)
    const summaries = getEvalSummaries(scopedRuns)

    if (summaries.length === 0) {
        return null
    }

    return (
        <div className="flex flex-row flex-wrap items-center gap-1.5">
            {summaries.map((summary) => {
                const { type, icon, label } = getEvalBadgeProps(summary.latestRun)
                return (
                    <Tooltip key={summary.latestRun.evaluation_id} title={<EvalTooltipContent {...summary} />}>
                        <LemonTag
                            type={type}
                            size="small"
                            icon={icon}
                            onClick={() => setViewMode(TraceViewMode.Evals)}
                            className="cursor-pointer"
                        >
                            {summary.latestRun.evaluation_name}: {label}
                        </LemonTag>
                    </Tooltip>
                )
            })}
        </div>
    )
}
