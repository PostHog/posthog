import type { EvaluationTemplate } from '../templates'

export const METHOD_TAGS: Record<EvaluationTemplate['evaluation_type'], string> = {
    llm_judge: 'LLM judge',
    hog: 'Hog',
    sentiment: 'Sentiment',
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

/** One line that says what a run returns, e.g. "Score from 1 to 5". */
export function templateOutputText(template: EvaluationTemplate): string {
    const { min, max, options = [], selection_mode } = template.output_config
    switch (template.output_type) {
        case 'boolean':
            return 'Pass or fail'
        case 'sentiment':
            return 'Positive, neutral, or negative'
        case 'numeric':
            return min != null && max != null ? `Score from ${min} to ${max}` : 'A number'
        case 'categorical':
            return `${selection_mode === 'multiple' ? 'Any' : 'One'} of ${options.length} categories`
    }
}
