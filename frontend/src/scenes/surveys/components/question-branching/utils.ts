import {
    MultipleSurveyQuestion,
    RatingSurveyQuestion,
    SurveyQuestion,
    SurveyQuestionBranchingType,
    SurveyQuestionType,
} from '~/types'

/**
 * Utility functions for survey question branching logic.
 * These helpers centralize the string parsing and value creation logic
 * to ensure consistency across components and logic layers.
 */

export const SPECIFIC_QUESTION_SEPARATOR = ':'

/**
 * Parses a specific question value back to its question index.
 * Format: "specific_question:questionIndex"
 * Returns null if the value is not a specific question type.
 */
export function parseSpecificQuestionValue(value: string): number | null {
    if (!value.startsWith(SurveyQuestionBranchingType.SpecificQuestion)) {
        return null
    }

    const parts = value.split(SPECIFIC_QUESTION_SEPARATOR)
    if (parts.length !== 2) {
        return null
    }

    const index = parseInt(parts[1])
    return isNaN(index) ? null : index
}

export function createSpecificQuestionValue(questionIndex: number): string {
    return `${SurveyQuestionBranchingType.SpecificQuestion}${SPECIFIC_QUESTION_SEPARATOR}${questionIndex}`
}

export function isSpecificQuestionValue(value: string): boolean {
    return value.startsWith(SurveyQuestionBranchingType.SpecificQuestion) && parseSpecificQuestionValue(value) !== null
}

export function getDefaultBranchingType(questionIndex: number, totalQuestions: number): SurveyQuestionBranchingType {
    return questionIndex < totalQuestions - 1
        ? SurveyQuestionBranchingType.NextQuestion
        : SurveyQuestionBranchingType.End
}

/**
 * Converts a branching configuration to a dropdown value.
 * Handles the special case of SpecificQuestion types that need index encoding.
 */
export function branchingConfigToDropdownValue(
    branchingType: SurveyQuestionBranchingType,
    specificQuestionIndex?: number
): string {
    if (branchingType === SurveyQuestionBranchingType.SpecificQuestion && specificQuestionIndex !== undefined) {
        return createSpecificQuestionValue(specificQuestionIndex)
    }
    return branchingType
}

export function isValidBranchingType(value: string): value is SurveyQuestionBranchingType {
    return Object.values(SurveyQuestionBranchingType).includes(value as SurveyQuestionBranchingType)
}

/**
 * Converts a dropdown value back to branching configuration.
 * Returns the branching type and optional specific question index.
 */
export function dropdownValueToBranchingConfig(value: string): {
    type: SurveyQuestionBranchingType
    specificQuestionIndex?: number
} {
    const specificQuestionIndex = parseSpecificQuestionValue(value)

    if (specificQuestionIndex !== null) {
        return {
            type: SurveyQuestionBranchingType.SpecificQuestion,
            specificQuestionIndex,
        }
    }

    // Validate the value before type casting
    if (!isValidBranchingType(value)) {
        console.error(`Invalid branching type: ${value}. Falling back to NextQuestion.`)
        return {
            type: SurveyQuestionBranchingType.NextQuestion,
        }
    }

    return {
        type: value,
    }
}

export function canQuestionHaveResponseBasedBranching(
    question: SurveyQuestion
): question is RatingSurveyQuestion | MultipleSurveyQuestion {
    return question.type === SurveyQuestionType.Rating || question.type === SurveyQuestionType.SingleChoice
}

export function createBranchingConfig(
    branchingType: SurveyQuestionBranchingType,
    specificQuestionIndex?: number
): SurveyQuestion['branching'] {
    switch (branchingType) {
        case SurveyQuestionBranchingType.NextQuestion:
            // NextQuestion is represented by the absence of branching config
            return undefined

        case SurveyQuestionBranchingType.End:
            return {
                type: SurveyQuestionBranchingType.End,
            }

        case SurveyQuestionBranchingType.ResponseBased:
            return {
                type: SurveyQuestionBranchingType.ResponseBased,
                responseValues: {},
            }

        case SurveyQuestionBranchingType.SpecificQuestion:
            if (specificQuestionIndex === undefined) {
                throw new Error('specificQuestionIndex is required for SpecificQuestion branching type')
            }
            return {
                type: SurveyQuestionBranchingType.SpecificQuestion,
                index: specificQuestionIndex,
            }

        default:
            throw new Error(`Unknown branching type: ${branchingType}`)
    }
}

/**
 * Remaps branching indices when the question array is mutated (reordered or deleted).
 *
 * `indexMap[oldIndex]` is the new position of the question that used to be at
 * `oldIndex`, or `null` if it was removed. Any branching that pointed at a removed
 * question is converted to default "Next question" (i.e. `branching` is dropped).
 *
 * Adding a question at the end is a no-op since existing indices stay valid.
 */
export function remapBranchingIndices(questions: SurveyQuestion[], indexMap: (number | null)[]): SurveyQuestion[] {
    const remapIndex = (index: number): number | null => {
        if (index < 0 || index >= indexMap.length) {
            return null
        }
        return indexMap[index]
    }

    return questions.map((question) => {
        if (!question.branching) {
            return question
        }

        if (question.branching.type === SurveyQuestionBranchingType.SpecificQuestion) {
            const remapped = remapIndex(question.branching.index)
            if (remapped === null) {
                // Target was deleted — fall back to default (Next question / End).
                const { branching, ...rest } = question
                return rest as SurveyQuestion
            }
            if (remapped === question.branching.index) {
                return question
            }
            return {
                ...question,
                branching: { ...question.branching, index: remapped },
            }
        }

        if (
            question.branching.type === SurveyQuestionBranchingType.ResponseBased &&
            'responseValues' in question.branching &&
            question.branching.responseValues
        ) {
            const originalEntries = Object.entries(question.branching.responseValues)
            const nextResponseValues: Record<string, number | SurveyQuestionBranchingType> = {}
            let changed = false
            for (const [response, target] of originalEntries) {
                if (typeof target === 'number') {
                    const remapped = remapIndex(target)
                    if (remapped === null) {
                        // Target was deleted — drop the mapping so it falls back to default.
                        changed = true
                        continue
                    }
                    if (remapped !== target) {
                        changed = true
                    }
                    nextResponseValues[response] = remapped
                } else {
                    nextResponseValues[response] = target
                }
            }
            if (!changed) {
                return question
            }
            // If we had mappings before and none survived, drop the whole branching block
            // so the question falls back to default routing (rather than keeping a
            // dangling ResponseBased config with empty rules).
            if (originalEntries.length > 0 && Object.keys(nextResponseValues).length === 0) {
                const { branching, ...rest } = question
                return rest as SurveyQuestion
            }
            return {
                ...question,
                branching: { ...question.branching, responseValues: nextResponseValues },
            }
        }

        return question
    })
}

/**
 * Builds an index map for a reorder operation that moved a single question
 * from `oldIndex` to `newIndex` within an array of `length` items.
 */
export function buildReorderIndexMap(length: number, oldIndex: number, newIndex: number): (number | null)[] {
    const map: (number | null)[] = Array.from({ length })
    for (let i = 0; i < length; i++) {
        if (i === oldIndex) {
            map[i] = newIndex
        } else if (oldIndex < newIndex && i > oldIndex && i <= newIndex) {
            map[i] = i - 1
        } else if (oldIndex > newIndex && i >= newIndex && i < oldIndex) {
            map[i] = i + 1
        } else {
            map[i] = i
        }
    }
    return map
}

/**
 * Builds an index map for a deletion at `deletedIndex` within an array of `length`
 * items. The deleted position maps to `null`; later positions shift left by one.
 */
export function buildDeleteIndexMap(length: number, deletedIndex: number): (number | null)[] {
    const map: (number | null)[] = Array.from({ length })
    for (let i = 0; i < length; i++) {
        if (i === deletedIndex) {
            map[i] = null
        } else if (i > deletedIndex) {
            map[i] = i - 1
        } else {
            map[i] = i
        }
    }
    return map
}
