import { HOG_EVAL_EXAMPLES } from './hogEvalExamples'
import { defaultEvaluationTemplates } from './templates'
import type { EvaluationConfig } from './types'

export interface HogSnippet {
    label: string
    source: string
    allowsNA?: boolean
}

const RETURN_SHAPES: Record<string, string> = {
    boolean: 'true or false',
    numeric: 'a number',
    categorical: 'a list of category keys',
}

/** What PostHog AI gets when asked to adapt the code: the code, what it must return, and where it runs. */
export function hogAdaptPrompt(evaluation: EvaluationConfig, source: string): string {
    const keys =
        evaluation.output_type === 'categorical'
            ? ` from ${(evaluation.output_config.options ?? []).map((option) => option.key).join(', ')}`
            : ''
    const naNote = evaluation.output_config.allows_na ? ', or null when it does not apply' : ''
    return [
        `Adapt this Hog evaluation code to my data. It runs on each ${evaluation.target} and must return ${RETURN_SHAPES[evaluation.output_type] ?? 'a result'}${keys}${naNote}.`,
        `Test it on recent ${evaluation.target}s with the Hog evaluation test tool, then give me the final code.`,
        '',
        '```',
        source.trim() || '// empty',
        '```',
    ].join('\n')
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
                  template.evaluation_type === 'hog' &&
                  template.output_type === evaluation.output_type &&
                  (template.target ?? 'generation') === evaluation.target
                      ? [
                            {
                                label: template.name,
                                source: template.source,
                                allowsNA: !!template.output_config.allows_na,
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
export function judgePromptsFor(evaluation: EvaluationConfig): { label: string; prompt: string }[] {
    if (evaluation.output_type === 'categorical') {
        return []
    }
    return defaultEvaluationTemplates.flatMap((template) =>
        template.evaluation_type === 'llm_judge' &&
        template.output_type === evaluation.output_type &&
        (template.target ?? 'generation') === evaluation.target
            ? [{ label: template.name, prompt: template.prompt }]
            : []
    )
}
