import { Link } from '@posthog/lemon-ui'

import { lowercaseFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { EventType } from '~/types'

import { EvaluationResultTag } from '../components/EvaluationResultTag'
import { MetadataTag } from '../components/MetadataTag'
import { normalizeEvaluationResultProperties } from '../utils'

export function EvaluationDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    const reasoning = eventProperties.$ai_evaluation_reasoning
    const evaluationName = eventProperties.$ai_evaluation_name
    const model = eventProperties.$ai_model ?? eventProperties.$ai_evaluation_model
    const traceId = eventProperties.$ai_trace_id
    const targetEventId = eventProperties.$ai_target_event_id
    const resultRun = {
        status: 'completed' as const,
        ...normalizeEvaluationResultProperties({
            rawResult: eventProperties.$ai_evaluation_result,
            rawApplicable: eventProperties.$ai_evaluation_applicable,
            rawEvaluationType: eventProperties.$ai_evaluation_runtime,
            rawResultType: eventProperties.$ai_evaluation_result_type,
            rawSentimentLabel: eventProperties.$ai_sentiment_label,
            rawSentimentScore: eventProperties.$ai_sentiment_score,
        }),
    }

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
                <EvaluationResultTag run={resultRun} />
                {evaluationName && (
                    <MetadataTag label="Evaluation" textToCopy={evaluationName}>
                        {evaluationName}
                    </MetadataTag>
                )}
                {typeof model === 'string' && model && (
                    <MetadataTag label="Judge model" textToCopy={lowercaseFirstLetter(model)}>
                        {lowercaseFirstLetter(model)}
                    </MetadataTag>
                )}
                {traceId && targetEventId && (
                    <MetadataTag label="Target event">
                        <Link to={urls.aiObservabilityTrace(traceId, { event: targetEventId })}>
                            {targetEventId.slice(0, 12)}...
                        </Link>
                    </MetadataTag>
                )}
            </div>

            {reasoning && (
                <div className="p-3 border rounded bg-surface-primary">
                    <div className="font-medium text-xs text-muted mb-1.5">REASONING</div>
                    <div className="text-sm whitespace-pre-wrap">{reasoning}</div>
                </div>
            )}
        </div>
    )
}
