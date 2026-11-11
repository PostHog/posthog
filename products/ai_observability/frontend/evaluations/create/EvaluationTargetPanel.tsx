import { useActions, useValues } from 'kea'

import { IconChat, IconMessage, IconStack } from '@posthog/icons'
import { LemonCollapse } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { EvaluationSettleConfig } from '../components/EvaluationSettleConfig'
import { evaluationOffersSessionTarget } from '../evaluationCapabilities'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { EvaluationTarget } from '../types'
import { EvaluationChoiceCards } from './EvaluationChoiceCards'
import { EvaluationLevelDiagram } from './EvaluationLevelDiagram'
import { settleSummary } from './evaluationSummary'

const SENTIMENT_ONLY_GENERATION = 'Sentiment reads one message at a time, so it runs on each generation.'

/** What one run covers, and how long a trace or session gets to finish first. */
export function EvaluationTargetPanel(): JSX.Element | null {
    const { evaluation } = useValues(llmEvaluationLogic)
    const { setEvaluationTarget } = useActions(llmEvaluationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!evaluation) {
        return null
    }
    const isSentiment = evaluation.evaluation_type === 'sentiment'
    const target: EvaluationTarget = isSentiment ? 'generation' : evaluation.target
    const offersSession = evaluationOffersSessionTarget(
        evaluation,
        !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVAL_SETTLING_STRATEGY]
    )
    const summary = settleSummary(evaluation)

    return (
        <div className="flex flex-col gap-3">
            <div className="grid grid-cols-1 items-start gap-4 @min-[40rem]/evaluation:grid-cols-2">
                <div className="flex flex-col gap-3 min-w-0">
                    <h4 className="mb-0 text-sm font-semibold">Choose what one run covers</h4>
                    <EvaluationChoiceCards<EvaluationTarget>
                        label="What one run covers"
                        value={target}
                        onChange={setEvaluationTarget}
                        dataAttr="llma-evaluation-create-target"
                        stacked
                        options={[
                            {
                                value: 'generation',
                                label: 'Each generation',
                                description: 'One LLM call. It runs as soon as the call arrives.',
                                icon: <IconMessage />,
                            },
                            {
                                value: 'trace',
                                label: 'Whole trace',
                                description:
                                    'One user request with all its LLM calls. Needs a trace ID ($ai_trace_id).',
                                icon: <IconStack />,
                                disabledReason: isSentiment ? SENTIMENT_ONLY_GENERATION : undefined,
                            },
                            ...(offersSession
                                ? [
                                      {
                                          value: 'session' as const,
                                          label: 'Whole session',
                                          description:
                                              'One conversation with all its traces. Needs a session ID ($ai_session_id) and a trace ID ($ai_trace_id).',
                                          icon: <IconChat />,
                                          disabledReason: isSentiment ? SENTIMENT_ONLY_GENERATION : undefined,
                                      },
                                  ]
                                : []),
                        ]}
                    />
                    {summary && (
                        <LemonCollapse
                            embedded
                            size="small"
                            panels={[
                                {
                                    key: 'advanced',
                                    header: (
                                        <span className="flex min-w-0 items-center gap-2 text-left">
                                            <span className="shrink-0 text-sm font-medium">Advanced</span>
                                            <span className="min-w-0 truncate text-xs text-secondary">{summary}</span>
                                        </span>
                                    ),
                                    content: (
                                        <div className="flex flex-col gap-4 pt-2">
                                            <EvaluationSettleConfig />
                                        </div>
                                    ),
                                    dataAttr: 'llma-evaluation-create-target-advanced',
                                },
                            ]}
                        />
                    )}
                </div>
                <EvaluationLevelDiagram level={target} />
            </div>
        </div>
    )
}
