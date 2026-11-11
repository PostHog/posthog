import type { AttachedContextItem } from '~/layout/ai/attachedContext'

import { HOG_EVAL_EXAMPLES } from './hogEvalExamples'
import { defaultEvaluationTemplates } from './templates'
import type { EvaluationConfig, EvaluationOutputConfig } from './types'

export interface HogSnippet {
    label: string
    source: string
    allowsNA?: boolean
    trueIsFailure?: boolean
}

export interface JudgePromptTemplate {
    label: string
    prompt: string
    trueIsFailure?: boolean
}

const RETURN_SHAPES: Record<string, string> = {
    boolean: 'true or false',
    numeric: 'a number',
    categorical: 'a list of category keys',
}

// Static on purpose: the code and setup travel as attached context, which the agent treats as untrusted data, so
// instructions hidden in a saved code comment never reach the message itself.
export const HOG_ADAPT_PROMPT =
    'Adapt the Hog evaluation code in the attached context to my data. Test it on recent runs with the Hog evaluation test tool, then give me the final code.'

export function hogAdaptContext(evaluation: EvaluationConfig, source: string): AttachedContextItem[] {
    const keys =
        evaluation.output_type === 'categorical'
            ? ` from ${(evaluation.output_config.options ?? []).map((option) => option.key).join(', ')}`
            : ''
    const naNote = evaluation.output_config.allows_na ? ', or null when it does not apply' : ''
    return [
        {
            type: 'text',
            label: 'Hog evaluation code',
            value: source.trim() || '// empty',
            hidden: true,
        },
        {
            type: 'text',
            label: 'Hog evaluation setup',
            value: `It runs on each ${evaluation.target} and must return ${RETURN_SHAPES[evaluation.output_type] ?? 'a result'}${keys}${naNote}.`,
            hidden: true,
        },
        // The agent cannot read an unsaved draft, so its own tests need the result rules and the traffic from here.
        {
            type: 'text',
            label: 'Hog evaluation test settings',
            value: JSON.stringify({
                output_type: evaluation.output_type,
                output_config: evaluation.output_config,
                target: evaluation.target,
                target_config: evaluation.target_config,
                conditions: evaluation.conditions,
            }),
            hidden: true,
        },
    ]
}

/** A score template's rubric names its own range, so it only fits an evaluation with no range or the same one. */
function scoreRangeFits(template: EvaluationOutputConfig, evaluation: EvaluationOutputConfig): boolean {
    const fits = (bound: 'min' | 'max'): boolean =>
        evaluation[bound] === null || evaluation[bound] === undefined || evaluation[bound] === template[bound]
    return fits('min') && fits('max')
}

function templateFits(
    template: { output_type: string; output_config: EvaluationOutputConfig; target?: string },
    evaluation: EvaluationConfig
): boolean {
    return (
        template.output_type === evaluation.output_type &&
        (template.target ?? 'generation') === evaluation.target &&
        (evaluation.output_type !== 'numeric' || scoreRangeFits(template.output_config, evaluation.output_config))
    )
}

/**
 * The code a Hog evaluation can start from: short starters for its return type, and the code of the Hog templates
 * that return the same type at the same level. A template written for traces reads fields a generation does not
 * have, so the level has to match too.
 */
export function hogSnippetsFor(evaluation: EvaluationConfig): { starters: HogSnippet[]; templates: HogSnippet[] } {
    const starters: HogSnippet[] =
        evaluation.output_type === 'categorical'
            ? (evaluation.output_config.options ?? [])
                  .slice(0, 2)
                  .map(({ key, label }) => ({ label, source: `return ['${key}'];` }))
            : evaluation.output_type === 'numeric'
              ? [
                    { label: 'Latency', source: 'return target.total_latency_seconds;', allowsNA: true },
                    { label: 'Cost', source: 'return target.total_cost_usd;', allowsNA: true },
                ]
              : HOG_EVAL_EXAMPLES.map(({ label, source }) => ({ label, source }))
    // Category templates return their own keys, which a different category list would not have.
    const templates =
        evaluation.output_type === 'categorical'
            ? []
            : defaultEvaluationTemplates.flatMap((template) =>
                  template.evaluation_type === 'hog' && templateFits(template, evaluation)
                      ? [
                            {
                                label: template.name,
                                source: template.source,
                                allowsNA: !!template.output_config.allows_na,
                                trueIsFailure: !!template.output_config.true_is_failure,
                            },
                        ]
                      : []
              )
    // Templates are built from these starters, so a template with a starter's code or name lists it once.
    const listed = new Set(templates.flatMap((template) => [template.label, template.source]))
    return {
        starters: starters.filter((starter) => !listed.has(starter.label) && !listed.has(starter.source)),
        templates,
    }
}

/**
 * The prompts of the LLM judge templates that return the same type at the same level. Category prompts name their
 * own categories, so a judge with its own category list gets none.
 */
export function judgePromptsFor(evaluation: EvaluationConfig): JudgePromptTemplate[] {
    if (evaluation.output_type === 'categorical') {
        return []
    }
    return defaultEvaluationTemplates.flatMap((template) =>
        template.evaluation_type === 'llm_judge' && templateFits(template, evaluation)
            ? [
                  {
                      label: template.name,
                      prompt: template.prompt,
                      trueIsFailure: !!template.output_config.true_is_failure,
                  },
              ]
            : []
    )
}
