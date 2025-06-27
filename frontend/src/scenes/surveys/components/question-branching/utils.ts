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
