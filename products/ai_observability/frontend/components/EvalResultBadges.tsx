import { LemonTagProps } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import { EvaluationRun } from '../evaluations/types'
import { EvaluationResultDisplayOptions, getEvaluationResultDisplay } from './EvaluationResultTag'

export interface EvalSummary {
    latestRun: EvaluationRun
    runCount: number
}

export function getEvalSummaries(runs: EvaluationRun[]): EvalSummary[] {
    const producedAt = (run: EvaluationRun): number => dayjs(run.start_time ?? run.timestamp).valueOf()
    const sorted = [...runs].sort((a, b) => producedAt(b) - producedAt(a))
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

export function getEvalBadgeProps(
    run: EvaluationRun,
    options: EvaluationResultDisplayOptions = {}
): {
    type: LemonTagProps['type']
    icon: JSX.Element
    label: string
} {
    const { type, icon, label } = getEvaluationResultDisplay(run, options)
    return { type, icon, label }
}

export function EvalTooltipContent({ latestRun, runCount }: EvalSummary): JSX.Element {
    return (
        <div className="max-w-80 space-y-1">
            <div className="font-semibold">{latestRun.evaluation_name}</div>
            <div className="text-xs opacity-75">
                {dayjs(latestRun.timestamp).fromNow()}
                {runCount > 1 && <> &middot; {pluralize(runCount, 'run', 'runs', true)} total</>}
            </div>
            <div className="text-sm">{latestRun.reasoning || 'No reasoning provided'}</div>
        </div>
    )
}
