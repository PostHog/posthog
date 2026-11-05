import { useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'

import * as stampApprovedPng from '@posthog/brand/hoggies/png/stamp-approved'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'

import { templateOutputText } from '../components/templateSummary'
import { evaluationReportLogic } from '../evaluationReportLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { ChecklistItem, ChecklistKey } from './creationChecklist'
import { methodText, reportText, targetText, triggerText } from './evaluationSummary'
import { EvaluationTrafficPreview } from './EvaluationTrafficPreview'

const ReadyHoggie = pngHoggie(stampApprovedPng)

export interface PreviewStep {
    key: string
    title: string
    /** pinned: the `llma-evaluation-create-part-*` data-attr and analytics value, read by the creation funnel. */
    part: string
    checks: ChecklistKey[]
}

/** "a daily report", "a report every 100 results", or "no reports". */
function reportPhrase(cadence: string): string {
    if (cadence === 'never') {
        return 'no reports'
    }
    return cadence.startsWith('every') ? `a report ${cadence}` : `a ${cadence} report`
}

/**
 * A live preview of the evaluation being set up: one sentence that says what it does, and the real traffic it
 * would run on with each run's result. Every part of the sentence opens the step that sets it.
 */
export function EvaluationLivePreview({
    steps,
    currentIndex,
    checklist,
    onGo,
}: {
    steps: PreviewStep[]
    currentIndex: number
    checklist: ChecklistItem[]
    onGo: (index: number) => void
}): JSX.Element | null {
    const { props } = useMountedLogic(llmEvaluationLogic)
    const { evaluation, usesDecisionModel, selectedModelName, selectedModel, isReportableEvaluation, isNewEvaluation } =
        useValues(llmEvaluationLogic)
    const { configDraft } = useValues(evaluationReportLogic({ evaluationId: props.evaluationId }))

    if (!evaluation) {
        return null
    }
    const open = (index: number): void => {
        if (index < 0 || index === currentIndex) {
            return
        }
        // pinned: analytics event name and properties, because the creation funnel reads them
        posthog.capture('llma evaluation create part opened', { part: steps[index].part, is_new: isNewEvaluation })
        onGo(index)
    }
    const part = (stepKey: string, text: string, missing?: ChecklistKey): JSX.Element => {
        const index = steps.findIndex((step) => step.key === stepKey)
        const step = steps[index]
        const todo = missing ? checklist.find((item) => item.key === missing && !item.done)?.todo : undefined
        if (!step) {
            return <span className="font-semibold">{text}</span>
        }
        return (
            <Tooltip title={todo}>
                <button
                    type="button"
                    onClick={() => open(index)}
                    aria-current={index === currentIndex ? 'step' : undefined}
                    className={cn(
                        '-mx-0.5 cursor-pointer rounded px-0.5 font-semibold underline decoration-dotted underline-offset-4 transition-colors motion-reduce:transition-none',
                        index === currentIndex ? 'bg-accent-highlight-light' : 'hover:bg-fill-highlight-100',
                        todo && 'text-danger'
                    )}
                    data-attr={`llma-evaluation-create-part-${step.part}`}
                >
                    {/* Keyed on the value, so a changed setting fades back in where you can see it. */}
                    <span key={text} className="animate-fade-in motion-reduce:animate-none">
                        {text}
                    </span>
                </button>
            </Tooltip>
        )
    }
    const lines = evaluation.evaluation_type === 'hog' ? evaluation.evaluation_config.source.trim().split('\n') : []
    const codeLines = lines.filter(Boolean).length
    const model = selectedModelName ?? selectedModel
    const cadence = reportText({ ...configDraft, enabled: configDraft.enabled && isReportableEvaluation })
    const todo = checklist.filter((item) => !item.done)

    return (
        <aside
            className="flex flex-col gap-4 rounded border bg-bg-light p-4 @min-[60rem]/evaluation:sticky @min-[60rem]/evaluation:top-4"
            aria-label="Preview"
            data-attr="llma-evaluation-create-live-preview"
        >
            <div className="flex flex-col gap-1.5">
                <h3 className="mb-0 truncate text-base font-semibold">
                    {evaluation.name.trim() || 'Untitled evaluation'}
                </h3>
                <p className="mb-0 text-sm leading-relaxed" data-attr="llma-evaluation-create-sentence">
                    {evaluation.evaluation_type === 'sentiment' ? (
                        <>
                            Rates {part('traffic', targetText(evaluation))} with{' '}
                            {part('name', methodText(evaluation, usesDecisionModel))} as positive, neutral, or negative.
                        </>
                    ) : (
                        <>
                            Checks {part('traffic', targetText(evaluation))} with{' '}
                            {evaluation.evaluation_type === 'hog' ? (
                                part(
                                    'check',
                                    codeLines > 0 ? `${pluralize(codeLines, 'line')} of Hog` : 'Hog code',
                                    'criteria'
                                )
                            ) : (
                                <>
                                    {part('name', methodText(evaluation, usesDecisionModel))} on{' '}
                                    {part('check', model ?? 'a model', 'model')}
                                </>
                            )}{' '}
                            and returns {part('output', templateOutputText(evaluation).toLowerCase(), 'result')}.
                        </>
                    )}{' '}
                    It runs on {part('traffic', triggerText(evaluation), 'sampling')} and sends{' '}
                    {part('reports', reportPhrase(cadence))}.
                </p>
            </div>
            <EvaluationTrafficPreview testable={steps[currentIndex]?.key === 'check'} />
            {todo.length === 0 && isNewEvaluation && (
                <div
                    className="flex items-center gap-3 border-t pt-3 animate-fade-in motion-reduce:animate-none"
                    data-attr="llma-evaluation-create-ready"
                >
                    <ReadyHoggie className="w-12 shrink-0" />
                    <span className="flex flex-col">
                        <span className="text-sm font-semibold">Ready to create</span>
                        <span className="text-xs text-secondary">Everything it needs is set.</span>
                    </span>
                </div>
            )}
            {todo.length > 0 && (
                <div className="flex flex-col gap-1 border-t pt-3" data-attr="llma-evaluation-create-todo">
                    <span className="text-xs font-semibold">{`${pluralize(todo.length, 'thing')} left`}</span>
                    {todo.map((item) => (
                        <Link
                            key={item.key}
                            className="text-xs"
                            onClick={() => open(steps.findIndex((step) => step.checks.includes(item.key)))}
                        >
                            {item.todo}
                        </Link>
                    ))}
                </div>
            )}
        </aside>
    )
}
