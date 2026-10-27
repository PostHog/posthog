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

type Part = 'method' | 'model' | 'target' | 'triggers' | 'reports'

const PANELS: Record<Part, () => JSX.Element | null> = {
    method: EvaluationMethodPanel,
    model: EvaluationModelPanel,
    target: EvaluationTargetPanel,
    triggers: EvaluationTriggersPanel,
    reports: EvaluationReportsPanel,
}

/**
 * The whole setup as one sentence: who checks, with which model, what one run covers, which traffic, and how often
 * a report arrives. Each part opens its settings under the sentence, one at a time.
 */
export function EvaluationSentence(): JSX.Element | null {
    const { props } = useMountedLogic(llmEvaluationLogic)
    const [open, setOpen] = useState<Part | null>(null)
    const { evaluation, usesDecisionModel, selectedModelName, selectedModel, isReportableEvaluation } =
        useValues(llmEvaluationLogic)
    const { configDraft } = useValues(evaluationReportLogic({ evaluationId: props.evaluationId }))

    if (!evaluation) {
        return null
    }
    const needsModel = evaluation.evaluation_type === 'llm_judge' && !selectedModel
    const part = (key: Part, text: React.ReactNode): JSX.Element => (
        <LemonButton
            type="secondary"
            size="small"
            active={open === key}
            sideIcon={<IconChevronDown className={cn('transition-transform', open === key && 'rotate-180')} />}
            onClick={() => {
                if (open !== key) {
                    // pinned: analytics event name and properties, because the creation funnel reads them
                    posthog.capture('llma evaluation create part opened', { part: key })
                }
                setOpen(open === key ? null : key)
            }}
            aria-expanded={open === key}
            className="inline-flex align-middle"
            data-attr={`llma-evaluation-create-part-${key}`}
        >
            {text}
        </LemonButton>
    )
    const Panel = open ? PANELS[open] : null

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
            <EvaluationVolumeEstimate />
        </section>
    )
}
