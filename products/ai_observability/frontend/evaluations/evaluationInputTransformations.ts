import { isValidRE2 } from 'lib/utils/regexp'

import type { EvaluationInputTransformation } from './types'

export const MAX_EVALUATION_INPUT_TRANSFORMATIONS = 20
export const MAX_EVALUATION_INPUT_TRANSFORMATION_PATTERN_LENGTH = 2000
export const MAX_EVALUATION_INPUT_TRANSFORMATION_REPLACEMENT_LENGTH = 10000

export function inputTransformationPatternError(pattern: string): string | null {
    if (!pattern) {
        return 'Enter a regular expression.'
    }
    if (!isValidRE2(pattern)) {
        return 'This pattern is not valid RE2 syntax.'
    }
    return null
}

export function inputTransformationsAreValid(transformations: EvaluationInputTransformation[]): boolean {
    return transformations.every(({ pattern }) => inputTransformationPatternError(pattern) === null)
}
