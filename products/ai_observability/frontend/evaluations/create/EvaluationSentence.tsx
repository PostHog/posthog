import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { templateOutputText } from '../components/templateSummary'
import type { EvaluationConfig } from '../types'
import type { ChecklistKey, PreviewStep } from './creationChecklist'
import { methodText, targetText, triggerText } from './evaluationSummary'

export interface EvaluationSentenceProps {
    evaluation: EvaluationConfig
    usesDecisionModel: boolean
    model: string
    reports: string
    steps: PreviewStep[]
    currentIndex: number
    /** What each unfinished checklist item still needs, by its key. */
    missing: Partial<Record<ChecklistKey, string>>
    onOpen: (index: number, part: string) => void
}

export function EvaluationSentence({
    evaluation,
    usesDecisionModel,
    model,
    reports,
    steps,
    currentIndex,
    missing,
    onOpen,
}: EvaluationSentenceProps): JSX.Element {
    /** `name` overrides the step's part where one step holds several parts, such as the target and the triggers. */
    const part = (stepKey: string, text: string, check?: ChecklistKey, name?: string): JSX.Element => {
        const index = steps.findIndex((step) => step.key === stepKey)
        const step = steps[index]
        if (!step) {
            return <span className="font-semibold">{text}</span>
        }
        const todo = check ? missing[check] : undefined
        const partName = name ?? step.part
        return (
            <Tooltip title={todo}>
                <button
                    type="button"
                    onClick={() => onOpen(index, partName)}
                    aria-current={index === currentIndex ? 'step' : undefined}
                    className={cn(
                        '-mx-0.5 cursor-pointer rounded px-0.5 font-semibold underline decoration-dotted underline-offset-4 transition-colors motion-reduce:transition-none',
                        index === currentIndex ? 'bg-accent-highlight-light' : 'hover:bg-fill-highlight-100',
                        todo && 'text-danger'
                    )}
                    data-attr={`llma-evaluation-create-part-${partName}`}
                >
                    {/* Keyed on the value, so a changed setting fades back in where you can see it. */}
                    <span key={text} className="animate-fade-in motion-reduce:animate-none">
                        {text}
                    </span>
                </button>
            </Tooltip>
        )
    }

    return (
        <p className="mb-0 text-sm leading-relaxed" data-attr="llma-evaluation-create-sentence">
            {evaluation.evaluation_type === 'sentiment' ? (
                <>
                    Rates {part('traffic', targetText(evaluation), undefined, 'target')} with{' '}
                    {part('name', methodText(evaluation, usesDecisionModel))} as positive, neutral, or negative.
                </>
            ) : (
                <>
                    Checks {part('traffic', targetText(evaluation), undefined, 'target')} with{' '}
                    {evaluation.evaluation_type === 'hog' ? (
                        part('check', 'Hog code', 'criteria', 'code')
                    ) : (
                        <>
                            {part('name', methodText(evaluation, usesDecisionModel))} on {part('check', model, 'model')}
                        </>
                    )}{' '}
                    and returns {part('output', templateOutputText(evaluation).toLowerCase(), 'result')}.
                </>
            )}{' '}
            It runs on {part('traffic', triggerText(evaluation), 'sampling')} and sends {part('reports', reports)}.
        </p>
    )
}
