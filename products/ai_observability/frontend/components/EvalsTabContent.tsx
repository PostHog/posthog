import { BuiltLogic, useActions, useMountedLogic, useValues } from 'kea'

import { IconCheckCircle, IconPlus, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { urls } from 'scenes/urls'

import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { aiObservabilityTraceLogic } from '../aiObservabilityTraceLogic'
import { generationEvaluationRunsLogic } from '../generationEvaluationRunsLogic'
import type { generationEvaluationRunsLogicType } from '../generationEvaluationRunsLogic'
import { llmEvaluationExecutionLogic } from '../llmEvaluationExecutionLogic'
import { formatLLMEventTitle } from '../utils'
import { GenerationEvalRunsTable } from './GenerationEvalRunsTable'

export function EvalsTabContent({
    traceId,
    generationEvent,
    distinctId,
}: {
    traceId: string
    generationEvent?: LLMTraceEvent
    distinctId?: string
}): JSX.Element {
    const runsLogic = generationEvaluationRunsLogic({ traceId })
    const traceLogic = useMountedLogic(aiObservabilityTraceLogic)

    useAttachedLogic(runsLogic, traceLogic)

    return (
        <EvalsTabContentInner
            generationEvent={generationEvent}
            distinctId={distinctId}
            generationRunsLogic={runsLogic}
        />
    )
}

function EvalsTabContentInner({
    generationEvent,
    distinctId,
    generationRunsLogic,
}: {
    generationEvent?: LLMTraceEvent
    distinctId?: string
    generationRunsLogic: BuiltLogic<generationEvaluationRunsLogicType>
}): JSX.Element {
    const { runEvaluation } = useActions(llmEvaluationExecutionLogic)
    const { evaluationRunLoading } = useValues(llmEvaluationExecutionLogic)
    const { refreshGenerationEvaluationRuns, setSelectedEvaluationId } = useActions(generationRunsLogic)
    const {
        evaluations,
        evaluationsLoading,
        generationEvaluationRunsLoading,
        runnableEvaluations,
        selectedEvaluation,
    } = useValues(generationRunsLogic)

    const hasNoEvaluations = !evaluationsLoading && !evaluations.some((e) => !e.deleted)

    return (
        <div className="py-4">
            <LemonBanner type="info" className="mb-4">
                Manually triggered evaluations typically appear within seconds, but may take a few minutes to process.
                Click Refresh to see new results.
            </LemonBanner>
            <div className="flex justify-between items-center mb-4">
                <div className="flex items-center gap-2">
                    {hasNoEvaluations ? (
                        <Link to={urls.aiObservabilityEvaluations()}>
                            <LemonButton type="primary" icon={<IconPlus />} size="small">
                                Create your first evaluation
                            </LemonButton>
                        </Link>
                    ) : generationEvent && !evaluationsLoading && runnableEvaluations.length === 0 ? (
                        <span className="text-muted text-sm">
                            No generation-target evaluations to run manually. Trace and session evaluations run
                            automatically.
                        </span>
                    ) : generationEvent ? (
                        <>
                            <LemonSelect
                                value={selectedEvaluation?.id ?? null}
                                onChange={setSelectedEvaluationId}
                                options={runnableEvaluations.map((evaluation) => ({
                                    value: evaluation.id,
                                    label: evaluation.name,
                                }))}
                                placeholder="Select an evaluation to run"
                                loading={evaluationsLoading}
                                className="w-80"
                            />
                            <LemonButton
                                type="primary"
                                size="small"
                                icon={<IconCheckCircle />}
                                onClick={() => {
                                    if (selectedEvaluation) {
                                        runEvaluation(
                                            selectedEvaluation.id,
                                            generationEvent.id,
                                            generationEvent.createdAt,
                                            generationEvent.event,
                                            distinctId
                                        )
                                    }
                                }}
                                loading={evaluationRunLoading}
                                disabledReason={!selectedEvaluation ? 'Select an evaluation first' : undefined}
                                data-attr="run-evaluation-manual"
                            >
                                Run Evaluation
                            </LemonButton>
                            <span className="text-muted text-sm">
                                Runs on generation {formatLLMEventTitle(generationEvent)}
                            </span>
                        </>
                    ) : null}
                </div>
                <LemonButton
                    type="secondary"
                    icon={<IconRefresh />}
                    onClick={refreshGenerationEvaluationRuns}
                    loading={generationEvaluationRunsLoading}
                    size="small"
                >
                    Refresh
                </LemonButton>
            </div>
            <GenerationEvalRunsTable generationRunsLogic={generationRunsLogic} />
        </div>
    )
}
