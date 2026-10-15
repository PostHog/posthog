import type { LemonTagType } from '@posthog/lemon-ui'

import type { EvaluationTemplate } from '../templates'

export const METHOD_TAGS: Record<EvaluationTemplate['evaluation_type'], { label: string; type: LemonTagType }> = {
    llm_judge: { label: 'LLM judge', type: 'caution' },
    hog: { label: 'Hog', type: 'option' },
    sentiment: { label: 'Sentiment', type: 'success' },
}

const METHOD_LABELS: Record<EvaluationTemplate['evaluation_type'], string> = {
    llm_judge: 'LLM judge',
    hog: 'Hog',
    sentiment: 'Built-in model',
}

const OUTPUT_LABELS: Record<EvaluationTemplate['output_type'], string> = {
    boolean: 'Pass or fail',
    numeric: 'Score',
    categorical: 'Categories',
    sentiment: 'Sentiment',
}

export function templateSummary(template: EvaluationTemplate): string {
    return `${OUTPUT_LABELS[template.output_type]} · ${METHOD_LABELS[template.evaluation_type]}`
}
