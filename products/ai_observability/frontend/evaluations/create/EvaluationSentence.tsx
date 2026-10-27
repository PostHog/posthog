import { useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'

import { evaluationReportLogic } from '../evaluationReportLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { methodText, reportText, targetText, triggerText } from './evaluationSummary'

export type SentencePart = 'method' | 'model' | 'target' | 'triggers' | 'reports'

/**
 * The whole setup as one sentence: who checks, with which model, what one run covers, which traffic, and how often
 * a report arrives. It is the overview above the steps: it marks the parts the current step edits, and a click on a
 * part goes to the step that edits it.
 */
export function EvaluationSentence({
    activeParts,
    onPartClick,
}: {
    activeParts: SentencePart[]
    onPartClick: (part: SentencePart) => void
}): JSX.Element | null {
    const { props } = useMountedLogic(llmEvaluationLogic)
    const { evaluation, usesDecisionModel, selectedModelName, selectedModel, isReportableEvaluation, isNewEvaluation } =
        useValues(llmEvaluationLogic)
    const { configDraft } = useValues(evaluationReportLogic({ evaluationId: props.evaluationId }))

    if (!evaluation) {
        return null
    }
    const needsModel = evaluation.evaluation_type === 'llm_judge' && !selectedModel
    const part = (key: SentencePart, text: React.ReactNode, missing = false): JSX.Element => (
        <LemonButton
            // The parts of the current step stand out, so the sentence shows where you are.
            type={activeParts.includes(key) ? 'primary' : 'secondary'}
            size="small"
            status={missing ? 'danger' : 'default'}
            active={activeParts.includes(key)}
            onClick={() => {
                if (!activeParts.includes(key)) {
                    // pinned: analytics event name and properties, because the creation funnel reads them
                    posthog.capture('llma evaluation create part opened', { part: key, is_new: isNewEvaluation })
                }
                onPartClick(key)
            }}
            className="inline-flex align-middle"
            data-attr={`llma-evaluation-create-part-${key}`}
        >
            {text}
        </LemonButton>
    )
    return (
        // One line, wrapping only when the page is narrow.
        <section
            className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-base"
            data-attr="llma-evaluation-create-sentence"
        >
            <span>Run</span>
            {part('method', methodText(evaluation, usesDecisionModel))}
            {evaluation.evaluation_type === 'llm_judge' && (
                <>
                    <span>with</span>
                    {part('model', needsModel ? 'pick a model' : (selectedModelName ?? selectedModel), needsModel)}
                </>
            )}
            <span>on</span>
            {/* Sentiment always reads single generations, so there is nothing to choose. */}
            {evaluation.evaluation_type === 'sentiment' ? (
                <span className="font-semibold">{targetText(evaluation)}</span>
            ) : (
                part('target', targetText(evaluation))
            )}
            <span>for</span>
            {part('triggers', triggerText(evaluation))}
            <span>and alert me</span>
            {part('reports', reportText({ ...configDraft, enabled: configDraft.enabled && isReportableEvaluation }))}
        </section>
    )
}
