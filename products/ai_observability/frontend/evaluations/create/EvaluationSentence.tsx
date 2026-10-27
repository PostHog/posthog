import { useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { EvaluationTriggersPanel } from '../components/EvaluationTriggersPanel'
import { evaluationReportLogic } from '../evaluationReportLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationMethodPanel } from './EvaluationMethodPanel'
import { EvaluationReportsPanel } from './EvaluationReportsPanel'
import { methodText, reportText, targetText, triggerText } from './evaluationSummary'
import { EvaluationTargetPanel } from './EvaluationTargetPanel'
import { EvaluationVolumeEstimate } from './EvaluationVolumeEstimate'

type Part = 'method' | 'target' | 'triggers' | 'reports'

const PANELS: Record<Part, () => JSX.Element | null> = {
    method: EvaluationMethodPanel,
    target: EvaluationTargetPanel,
    triggers: EvaluationTriggersPanel,
    reports: EvaluationReportsPanel,
}

/**
 * The whole setup as one sentence: who checks, what one run covers, which traffic, and the reports.
 * Each part opens its settings under the sentence, one at a time.
 */
export function EvaluationSentence(): JSX.Element | null {
    const [open, setOpen] = useState<Part | null>(null)
    const { evaluation, usesDecisionModel, selectedModelName, selectedModel, isReportableEvaluation } =
        useValues(llmEvaluationLogic)
    const { configDraft } = useValues(evaluationReportLogic({ evaluationId: 'new' }))

    if (!evaluation) {
        return null
    }
    const needsModel = evaluation.evaluation_type === 'llm_judge' && !selectedModel
    const part = (key: Part, text: string, warning = false): JSX.Element => (
        <LemonButton
            type="secondary"
            size="small"
            active={open === key}
            status={warning ? 'danger' : 'default'}
            sideIcon={<IconChevronDown className={cn('transition-transform', open === key && 'rotate-180')} />}
            onClick={() => setOpen(open === key ? null : key)}
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
            <p className="mb-0 text-lg leading-[2.5rem] flex flex-wrap items-center gap-x-2">
                <span>Run</span>
                {part(
                    'method',
                    needsModel
                        ? `${methodText(evaluation, usesDecisionModel)}, pick a model`
                        : methodText(evaluation, usesDecisionModel, selectedModelName ?? (selectedModel || undefined)),
                    needsModel
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
                <span>with</span>
                {part(
                    'reports',
                    reportText({ ...configDraft, enabled: configDraft.enabled && isReportableEvaluation })
                )}
            </p>
            {Panel && (
                <div className="border rounded p-4 bg-surface-primary">
                    <Panel />
                </div>
            )}
            <EvaluationVolumeEstimate />
        </section>
    )
}
