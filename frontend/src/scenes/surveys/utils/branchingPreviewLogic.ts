import {
    BasicSurveyQuestion,
    LinkSurveyQuestion,
    MultipleSurveyQuestion,
    RatingSurveyQuestion,
    SurveyQuestionBranchingType,
    SurveyQuestionType,
} from '~/types'

export function getRatingScaleResponse(response: number, scale: number): string {
    switch (scale) {
        case 10: // NPS scale
            if (response <= 6) {
                return 'detractors'
            }
            if (response <= 8) {
                return 'passives'
            }
            return 'promoters'
        case 7: // 7-point likert scale
            if (response <= 3) {
                return 'negative'
            }
            if (response === 4) {
                return 'neutral'
            }
            return 'positive'
        case 5: // 5-point scale
            if (response <= 2) {
                return 'negative'
            }
            if (response === 3) {
                return 'neutral'
            }
            return 'positive'
        default:
            return 'neutral'
    }
}

export function getNextQuestionIndex(
    currentQuestion: RatingSurveyQuestion | MultipleSurveyQuestion | BasicSurveyQuestion | LinkSurveyQuestion,
    confirmationMessageIndex: number,
    currentIndex: number,
    response: string | string[] | number | null
): number {
    if (!currentQuestion.branching || currentQuestion.branching.type === SurveyQuestionBranchingType.NextQuestion) {
        return currentIndex + 1
    }

    if (currentQuestion.branching.type === SurveyQuestionBranchingType.End) {
        return confirmationMessageIndex
    }

    if (currentQuestion.branching.type === SurveyQuestionBranchingType.SpecificQuestion) {
        return currentQuestion.branching.index
    }

    if (currentQuestion.branching.type === SurveyQuestionBranchingType.ResponseBased) {
        if (currentQuestion.type === SurveyQuestionType.Rating) {
            // safe to assume response as number, since it's a Rating question
            const responseKey = getRatingScaleResponse(response as number, currentQuestion.scale)
            if (currentQuestion.branching.responseValues[responseKey] === SurveyQuestionBranchingType.End) {
                return confirmationMessageIndex
            }
            return currentQuestion.branching.responseValues[responseKey]
        }
        if (currentQuestion.type === SurveyQuestionType.SingleChoice) {
            // safe to assume response as string, since it's a SingleChoice question
            const responseKey = currentQuestion.choices.indexOf(response as string)
            if (currentQuestion.branching.responseValues[responseKey] === SurveyQuestionBranchingType.End) {
                return confirmationMessageIndex
            }
            return currentQuestion.branching.responseValues[responseKey]
        }
    }

    return currentIndex + 1
}
