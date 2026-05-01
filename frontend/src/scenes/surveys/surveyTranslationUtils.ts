import { Survey, SurveyAppearance, SurveyQuestion, SurveyQuestionType } from '~/types'

import { NewSurvey } from './constants'

export function getSurveyWithTranslatedContent<TSurvey extends Survey | NewSurvey>(
    survey: TSurvey,
    language: string | null
): TSurvey {
    const translation = language ? survey.translations?.[language] : null

    if (!language || !translation) {
        return survey
    }

    const appearanceUpdates: Partial<SurveyAppearance> = {}
    if (translation.thankYouMessageHeader) {
        appearanceUpdates.thankYouMessageHeader = translation.thankYouMessageHeader
    }
    if (translation.thankYouMessageDescription) {
        appearanceUpdates.thankYouMessageDescription = translation.thankYouMessageDescription
    }
    if (translation.thankYouMessageCloseButtonText) {
        appearanceUpdates.thankYouMessageCloseButtonText = translation.thankYouMessageCloseButtonText
    }

    return {
        ...survey,
        ...(translation.name ? { name: translation.name } : {}),
        ...(Object.keys(appearanceUpdates).length > 0
            ? {
                  appearance: {
                      ...survey.appearance,
                      ...appearanceUpdates,
                  },
              }
            : {}),
        questions: survey.questions.map((question): SurveyQuestion => {
            const questionTranslation = question.translations?.[language]

            if (!questionTranslation) {
                return question
            }

            const translatedFields = {
                question: questionTranslation.question || question.question,
                description: questionTranslation.description || question.description,
                buttonText: questionTranslation.buttonText || question.buttonText,
            }

            if (
                question.type === SurveyQuestionType.SingleChoice ||
                question.type === SurveyQuestionType.MultipleChoice
            ) {
                return {
                    ...question,
                    ...translatedFields,
                    choices: questionTranslation.choices || question.choices,
                }
            }

            if (question.type === SurveyQuestionType.Link) {
                return {
                    ...question,
                    ...translatedFields,
                    link: questionTranslation.link || question.link,
                }
            }

            if (question.type === SurveyQuestionType.Rating) {
                return {
                    ...question,
                    ...translatedFields,
                    lowerBoundLabel: questionTranslation.lowerBoundLabel || question.lowerBoundLabel,
                    upperBoundLabel: questionTranslation.upperBoundLabel || question.upperBoundLabel,
                }
            }

            return {
                ...question,
                ...translatedFields,
            }
        }),
    } as TSurvey
}
