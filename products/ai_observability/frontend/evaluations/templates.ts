import templateData from '../../shared/evaluation_templates.json'
import { getHogEvalExample } from './hogEvalExamples'
import type { EvaluationOutputConfig, EvaluationTarget } from './types'

export const EVALUATION_TEMPLATE_ICONS = [
    'target',
    'thumbs-up',
    'eye',
    'alert-triangle',
    'code',
    'search',
    'wrench',
    'emoji',
    'star',
    'bug',
    'check-circle',
    'chat',
    'shield',
    'lock',
    'thumbs-down',
    'piggy-bank',
    'clock',
    'refresh',
    'flag',
    'undo',
] as const
export type EvaluationTemplateIcon = (typeof EVALUATION_TEMPLATE_ICONS)[number]

export const EVALUATION_TEMPLATE_CATEGORIES = ['quality', 'safety', 'agents', 'users', 'cost_speed'] as const
export type EvaluationTemplateCategory = (typeof EVALUATION_TEMPLATE_CATEGORIES)[number]

interface BaseTemplate {
    key: string
    name: string
    description: string
    icon: EvaluationTemplateIcon
    category: EvaluationTemplateCategory
    /** Defaults to 'generation'. */
    target?: EvaluationTarget
}

interface ScoredTemplate extends BaseTemplate {
    output_type: 'boolean' | 'numeric' | 'categorical'
    output_config: EvaluationOutputConfig
}

export interface LLMJudgeTemplate extends ScoredTemplate {
    evaluation_type: 'llm_judge'
    prompt: string
}

export interface HogTemplate extends ScoredTemplate {
    evaluation_type: 'hog'
    source: string
}

export interface SentimentTemplate extends BaseTemplate {
    evaluation_type: 'sentiment'
    output_type: 'sentiment'
    output_config: EvaluationOutputConfig
}

export type EvaluationTemplate = LLMJudgeTemplate | HogTemplate | SentimentTemplate

interface StoredTemplate {
    /** Key of a shared Hog example that holds the template's source. */
    hog_example?: string
    _note?: string
}

// Template keys reach URLs (?template=) and the `llm evaluation template selected` event, so never rename one.
// The backend reads the same catalog to suggest templates, so templates are edited in the shared JSON file.
export const defaultEvaluationTemplates: readonly EvaluationTemplate[] = templateData.map((entry) => {
    const { hog_example, _note, ...template } = entry as StoredTemplate & Record<string, unknown>
    const resolved = hog_example ? { ...template, source: getHogEvalExample(hog_example).source } : template
    // A JSON import widens literal unions such as `icon` to string, so templates.test.ts checks each entry.
    return resolved as unknown as EvaluationTemplate
})

export type EvaluationTemplateKey = (typeof defaultEvaluationTemplates)[number]['key']
