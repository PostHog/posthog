import { useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { EvaluationTriggersPanel } from '../components/EvaluationTriggersPanel'
import { evaluationReportLogic } from '../evaluationReportLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationMethodPanel } from './EvaluationMethodPanel'
import { EvaluationModelPanel } from './EvaluationModelPanel'
import { EvaluationReportsPanel } from './EvaluationReportsPanel'
import { methodText, reportText, targetText, triggerText } from './evaluationSummary'
import { EvaluationTargetPanel } from './EvaluationTargetPanel'
import { EvaluationVolumeEstimate } from './EvaluationVolumeEstimate'

export type SentencePart = 'method' | 'model' | 'target' | 'triggers' | 'reports'

const PANELS: Record<SentencePart, () => JSX.Element | null> = {
    method: EvaluationMethodPanel,
    model: EvaluationModelPanel,
    target: EvaluationTargetPanel,
    triggers: EvaluationTriggersPanel,
    reports: EvaluationReportsPanel,
}

/**
 * The whole setup as one sentence: who checks, with which model, what one run covers, which traffic, and how often
 * a report arrives. By default each part opens its settings under the sentence, one at a time. Given `onPartClick`,
 * the sentence is an overview instead: it marks the parts the current step edits, and a click goes to their step.
 */
export function EvaluationSentence({
    activeParts,
    onPartClick,
}: {
    activeParts?: SentencePart[]
    onPartClick?: (part: SentencePart) => void
} = {}): JSX.Element | null {
    const { props } = useMountedLogic(llmEvaluationLogic)
    const [open, setOpen] = useState<SentencePart | null>(null)
    const { evaluation, usesDecisionModel, selectedModelName, selectedModel, isReportableEvaluation } =
        useValues(llmEvaluationLogic)
    const { configDraft } = useValues(evaluationReportLogic({ evaluationId: props.evaluationId }))

    if (!evaluation) {
        return null
    }
    const needsModel = evaluation.evaluation_type === 'llm_judge' && !selectedModel
    const isActive = (key: SentencePart): boolean => (onPartClick ? !!activeParts?.includes(key) : open === key)
    const part = (key: SentencePart, text: React.ReactNode): JSX.Element => (
        <LemonButton
            // As an overview, the parts of the current step stand out, so the sentence shows where you are.
            type={onPartClick && isActive(key) ? 'primary' : 'secondary'}
            size="small"
            active={isActive(key)}
            sideIcon={
                onPartClick ? undefined : (
                    <IconChevronDown className={cn('transition-transform', open === key && 'rotate-180')} />
                )
            }
            onClick={() => {
                if (!isActive(key)) {
                    // pinned: analytics event name and properties, because the creation funnel reads them
                    posthog.capture('llma evaluation create part opened', { part: key })
                }
                if (onPartClick) {
                    onPartClick(key)
                } else {
                    setOpen(open === key ? null : key)
                }
            }}
            aria-expanded={onPartClick ? undefined : open === key}
            className="inline-flex align-middle"
            data-attr={`llma-evaluation-create-part-${key}`}
        >
            {text}
        </LemonButton>
    )
    const Panel = open && !onPartClick ? PANELS[open] : null

    return (
        <section className="flex flex-col gap-3" data-attr="llma-evaluation-create-sentence">
            <div className="flex flex-col gap-1 text-lg">
                <p className="mb-0 leading-[2.5rem] flex flex-wrap items-center gap-x-2">
                    <span>Run</span>
                    {part('method', methodText(evaluation, usesDecisionModel))}
                    {evaluation.evaluation_type === 'llm_judge' && (
                        <>
                            <span>with</span>
                            {part(
                                'model',
                                // Reads as an empty field, so it does not look like the part that is open.
                                needsModel ? (
                                    <span className="text-secondary">pick a model</span>
                                ) : (
                                    (selectedModelName ?? selectedModel)
                                )
                            )}
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
                </p>
                <p className="mb-0 leading-[2.5rem] flex flex-wrap items-center gap-x-2">
                    <span>and alert me</span>
                    {part(
                        'reports',
                        reportText({ ...configDraft, enabled: configDraft.enabled && isReportableEvaluation })
                    )}
                </p>
            </div>
            {Panel && (
                <div className="border rounded p-4 bg-surface-primary">
                    <Panel />
                </div>
            )}
            {!onPartClick && <EvaluationVolumeEstimate />}
        </section>
    )
}
