import { BuiltLogic, useActions, useMountedLogic, useValues } from 'kea'

import { IconCheckCircle, IconPlus, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { urls } from 'scenes/urls'

import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { aiObservabilityTraceLogic } from '../aiObservabilityTraceLogic'
import { llmEvaluationsLogic } from '../evaluations/llmEvaluationsLogic'
import { generationEvaluationRunsLogic } from '../generationEvaluationRunsLogic'
import { generationEvaluationRunsLogicType } from '../generationEvaluationRunsLogicType'
import { llmEvaluationExecutionLogic } from '../llmEvaluationExecutionLogic'
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
    const runsLogic = generationEvaluationRunsLogic({ lookupBy: 'trace', traceId })
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
    const { evaluations, evaluationsLoading } = useValues(llmEvaluationsLogic)
    const { runEvaluation } = useActions(llmEvaluationExecutionLogic)
    const { evaluationRunLoading } = useValues(llmEvaluationExecutionLogic)
    const { refreshGenerationEvaluationRuns, setSelectedEvaluationId } = useActions(generationRunsLogic)
    const { generationEvaluationRunsLoading, selectedEvaluationId } = useValues(generationRunsLogic)

    const availableEvaluations = evaluations?.filter((e) => !e.deleted) || []
    // Manual runs go through the generation workflow, so only generation-target evals
    // can be triggered from here, and only when there is a generation to point them at.
    const runnableEvaluations = generationEvent ? availableEvaluations.filter((e) => e.target !== 'trace') : []
    const hasNoEvaluations = !evaluationsLoading && availableEvaluations.length === 0

    return (
        <div className="py-4">
            <LemonBanner type="info" className="mb-4">
                Manually triggered evaluations typically appear within seconds, but may take a few minutes to process.
                Click Refresh to see new results.
            </LemonBanner>
            <div className="flex justify-between items-center mb-4">
                <div className="flex gap-2">
                    {hasNoEvaluations ? (
                        <Link to={urls.aiObservabilityEvaluations()}>
                            <LemonButton type="primary" icon={<IconPlus />} size="small">
                                Create your first evaluation
                            </LemonButton>
                        </Link>
                    ) : generationEvent && runnableEvaluations.length > 0 ? (
                        <>
                            <LemonSelect
                                value={selectedEvaluationId}
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
                                    if (selectedEvaluationId) {
                                        runEvaluation(
                                            selectedEvaluationId,
                                            generationEvent.id,
                                            generationEvent.createdAt,
                                            generationEvent.event,
                                            distinctId
                                        )
                                    }
                                }}
                                loading={evaluationRunLoading}
                                disabledReason={!selectedEvaluationId ? 'Select an evaluation first' : undefined}
                                data-attr="run-evaluation-manual"
                            >
                                Run Evaluation
                            </LemonButton>
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
