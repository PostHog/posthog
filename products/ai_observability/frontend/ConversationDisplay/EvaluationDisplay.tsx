import { Link } from '@posthog/lemon-ui'

import { lowercaseFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

import { EventType } from '~/types'

import { EvaluationResultTag } from '../components/EvaluationResultTag'
import { MetadataTag } from '../components/MetadataTag'

function parseOptionalNumber(value: unknown): number | null {
    if (value === null || value === undefined) {
        return null
    }
    const parsed = typeof value === 'number' ? value : Number(value)
    return Number.isFinite(parsed) ? parsed : null
}

export function EvaluationDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    const rawResult = eventProperties.$ai_evaluation_result
    const rawApplicable = eventProperties.$ai_evaluation_applicable
    const evaluationType: 'sentiment' | undefined =
        eventProperties.$ai_evaluation_runtime === 'sentiment' ? 'sentiment' : undefined
    // Check if result is explicitly true (handles both boolean and string 'true')
    const isPass = rawResult === true || rawResult === 'true' || rawResult === 'True' || rawResult === '1'
    // N/A when backend explicitly sets applicable to false (handle string 'false' from HogQL)
    const isNA = rawApplicable === false || rawApplicable === 'false'
    const reasoning = eventProperties.$ai_evaluation_reasoning
    const evaluationName = eventProperties.$ai_evaluation_name
    const model = eventProperties.$ai_model ?? eventProperties.$ai_evaluation_model
    const traceId = eventProperties.$ai_trace_id
    const targetEventId = eventProperties.$ai_target_event_id
    const result = isNA || rawResult === null || rawResult === undefined ? null : isPass
    const sentimentLabel =
        typeof eventProperties.$ai_sentiment_label === 'string' ? eventProperties.$ai_sentiment_label : null
    const rawResultType = eventProperties.$ai_evaluation_result_type
    const resultType =
        rawResultType === 'sentiment' || rawResultType === 'boolean'
            ? rawResultType
            : evaluationType === 'sentiment' || sentimentLabel
              ? 'sentiment'
              : 'boolean'
    const resultRun = {
        status: 'completed' as const,
        result,
        result_type: resultType,
        evaluation_type: evaluationType,
        sentiment_label: sentimentLabel,
        sentiment_score: parseOptionalNumber(eventProperties.$ai_sentiment_score),
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
