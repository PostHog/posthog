import examples from './hogEvalExamples.json'

export interface HogEvalExample {
    key: string
    label: string
    source: string
}

export const HOG_EVAL_EXAMPLES: readonly HogEvalExample[] = examples

export function getHogEvalExample(key: string): HogEvalExample {
    const example = HOG_EVAL_EXAMPLES.find((candidate) => candidate.key === key)
    if (!example) {
        throw new Error(`Unknown Hog evaluation example: ${key}`)
    }
    return example
}
