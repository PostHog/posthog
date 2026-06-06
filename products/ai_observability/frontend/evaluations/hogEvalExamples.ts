import examples from './hogEvalExamples.json'

export interface HogEvalExample {
    label: string
    source: string
}

export const HOG_EVAL_EXAMPLES: HogEvalExample[] = examples
