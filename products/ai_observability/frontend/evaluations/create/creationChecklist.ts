import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'

import { templateOutputText } from '../components/templateSummary'
import { categoricalOutputConfigError } from '../constants'
import type { EvaluationConfig, EvaluationOutputConfig } from '../types'
import { triggerText } from './evaluationSummary'

export type ChecklistKey = 'name' | 'criteria' | 'result' | 'model' | 'sampling'

export interface ChecklistItem {
    key: ChecklistKey
    label: string
    done: boolean
    /** What to do next when the item is not done. Also the reason the create button is disabled. */
    todo: string
    /** What was chosen, shown once the item is done. */
    summary?: string
    /** Something about a done item that deserves a second look. It does not block creating. */
    warning?: string
}

export interface PreviewStep {
    key: string
    title: string
    /** pinned: the `llma-evaluation-create-part-*` data-attr and analytics value, read by the creation funnel. */
    part: string
    checks: ChecklistKey[]
}

export interface ChecklistInput {
    evaluation: EvaluationConfig
    /** The output settings' validation error, or null when they are valid. */
    resultError: string | null
    modelSelectionRequired: boolean
    hasSelectedModel: boolean
    /** False when no configured provider offers a model to pick. */
    hasAvailableModels: boolean
    hasUnsetSampling: boolean
    /** Why the Hog code does not compile, from the preview's test, or null when it does. */
    codeError: string | null
    everyTestErrored: boolean
    /** Set when the filters match traffic that the target can never run on, such as sessions with no session ID. */
    wouldNotRun: string | null
}

const CRITERIA: Record<'llm_judge' | 'hog', { label: string; todo: string }> = {
    llm_judge: { label: 'Evaluation prompt', todo: 'Write the prompt the judge follows' },
    hog: { label: 'Code', todo: 'Add the Hog code that returns the result' },
}

/** What a new evaluation still needs before it can be created, in the order the page asks for it. */
export function creationChecklist(input: ChecklistInput): ChecklistItem[] {
    const { evaluation } = input
    const items: ChecklistItem[] = [
        {
            key: 'name',
            label: 'Name',
            done: evaluation.name.trim().length > 0,
            todo: 'Give the evaluation a name',
            summary: evaluation.name.trim(),
        },
    ]
    if (evaluation.evaluation_type !== 'sentiment') {
        items.push({
            key: 'result',
            label: 'Result',
            done: input.resultError === null,
            todo: input.resultError ?? '',
            summary: templateOutputText(evaluation),
        })
    }
    items.push({
        key: 'sampling',
        label: 'Sampling',
        done: !input.hasUnsetSampling,
        todo: 'Set a sampling percentage between 0.1% and 100%',
        summary: capitalizeFirstLetter(triggerText(evaluation)),
        warning: input.wouldNotRun ?? undefined,
    })
    if (evaluation.evaluation_type === 'llm_judge' || evaluation.evaluation_type === 'hog') {
        const content =
            evaluation.evaluation_type === 'llm_judge'
                ? evaluation.evaluation_config.prompt
                : evaluation.evaluation_config.source
        // Code that does not compile cannot be saved, so it counts as missing until it is fixed.
        const codeError = evaluation.evaluation_type === 'hog' ? input.codeError : null
        items.push({
            key: 'criteria',
            done: content.trim().length > 0 && !codeError,
            summary:
                evaluation.evaluation_type === 'llm_judge'
                    ? content.trim().split('\n')[0]
                    : pluralize(content.trim().split('\n').length, 'line') + ' of code',
            ...CRITERIA[evaluation.evaluation_type],
            ...(codeError ? { todo: 'Fix the code so it compiles' } : {}),
            // The runs may fail for a reason outside the evaluation, so this asks for a look and does not block.
            warning: input.everyTestErrored ? 'Every test run returned an error' : undefined,
        })
    }
    if (input.modelSelectionRequired) {
        items.push({
            key: 'model',
            label: 'Judge model',
            done: input.hasSelectedModel,
            todo: input.hasAvailableModels
                ? 'Pick the model that judges each run'
                : 'Add an API key for an AI provider, then pick a model',
            summary: evaluation.model_configuration?.model,
        })
    }
    return items
}

/** The categories' validation error in the page's terms. The page derives keys from names, so it never mentions keys. */
export function categoryResultError(config: EvaluationOutputConfig): string | null {
    const options = config.options ?? []
    if (options.length === 0) {
        return 'Add at least one category'
    }
    if (options.some((option) => !option.label.trim() || !option.key)) {
        return 'Give every category a name with at least one letter or number'
    }
    if (new Set(options.map((option) => option.key)).size !== options.length) {
        return 'Give each category a different name'
    }
    return categoricalOutputConfigError(config)
}
