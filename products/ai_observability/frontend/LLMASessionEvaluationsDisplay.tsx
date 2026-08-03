import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { aiObservabilitySessionEvaluationsLogic } from './aiObservabilitySessionEvaluationsLogic'
import { EvaluationResultTag } from './components/EvaluationResultTag'

interface LLMASessionEvaluationsDisplayProps {
    sessionId: string
}

export function LLMASessionEvaluationsDisplay({ sessionId }: LLMASessionEvaluationsDisplayProps): JSX.Element | null {
    const { sessionEvaluations } = useValues(aiObservabilitySessionEvaluationsLogic({ sessionId }))

    if (sessionEvaluations.length === 0) {
        return null
    }

    return (
        <>
            {sessionEvaluations.map((evaluation, index) => (
                <Tooltip
                    key={`session-evaluation-${index}`}
                    title={
                        <>
                            <div className="font-medium">{evaluation.evaluationName}</div>
                            <div>{evaluation.reasoning}</div>
                        </>
                    }
                >
                    <span>
                        <EvaluationResultTag
                            run={{
                                status: 'completed',
                                result: evaluation.verdict,
                                result_type: 'boolean',
                                skipped: evaluation.skipped,
                            }}
                            size="medium"
                        />
                    </span>
                </Tooltip>
            ))}
        </>
    )
}
