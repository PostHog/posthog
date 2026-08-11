import { useValues } from 'kea'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { aiObservabilitySessionEvaluationsLogic } from './aiObservabilitySessionEvaluationsLogic'
import { EvalTooltipContent, getEvalBadgeProps, getEvalSummaries } from './components/EvalResultBadges'

interface LLMASessionEvaluationsDisplayProps {
    sessionId: string
}

export function LLMASessionEvaluationsDisplay({ sessionId }: LLMASessionEvaluationsDisplayProps): JSX.Element | null {
    const { sessionEvaluations } = useValues(aiObservabilitySessionEvaluationsLogic({ sessionId }))

    // A session that resumes after being evaluated can be graded again; collapse to the newest
    // verdict per evaluation so a stale tag never sits beside a fresh one. Same helper the trace
    // and generation surfaces use, so the tooltip and badge read identically everywhere.
    const summaries = getEvalSummaries(sessionEvaluations)

    if (summaries.length === 0) {
        return null
    }

    return (
        <>
            {summaries.map((summary) => {
                const { type, icon, label } = getEvalBadgeProps(summary.latestRun)
                return (
                    <Tooltip key={summary.latestRun.evaluation_id} title={<EvalTooltipContent {...summary} />}>
                        <span>
                            <LemonTag type={type} icon={icon} size="medium">
                                {label}
                            </LemonTag>
                        </span>
                    </Tooltip>
                )
            })}
        </>
    )
}
