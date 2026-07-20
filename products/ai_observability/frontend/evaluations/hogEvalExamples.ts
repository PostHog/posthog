import examples from './hogEvalExamples.json'

export interface HogEvalExample {
    label: string
    source: string
}

export const HOG_EVAL_EXAMPLES: HogEvalExample[] = examples

// Look up an example's Hog source by its label so templates can reuse the same
// snippets shown in the code editor instead of duplicating them.
export function getHogEvalExampleSource(label: string): string {
    const example = HOG_EVAL_EXAMPLES.find((e) => e.label === label)
    if (!example) {
        throw new Error(`Unknown Hog eval example: "${label}"`)
    }
    return example.source
}
