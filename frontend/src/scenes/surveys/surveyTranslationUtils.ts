import { MultipleSurveyQuestion, Survey, SurveyAppearance, SurveyQuestion, SurveyQuestionType } from '~/types'

import { NewSurvey } from './constants'

// Respondents are shown choices in their own language and submit the translated text, so a
// translated choice has to map back to its base-language choice (matched by position) to be
// recognised as a predefined answer rather than a free-text "Other" response.
//
// Keep in sync with the backend twin `build_choice_translation_map` in
// products/surveys/backend/responses/fetch_rows.py — both must agree on the positional mapping,
// the length guard, and the base-choice-wins seeding order.
export function buildChoiceTranslationMap(question: MultipleSurveyQuestion): Map<string, string> {
    const baseChoices = question.choices ?? []
    const map = new Map<string, string>()

    for (const translation of Object.values(question.translations ?? {})) {
        const translatedChoices = translation.choices
        // Positional mapping is only trustworthy when the arrays line up 1:1. If a choice was
        // added or removed without updating this translation, the lengths diverge and index i no
        // longer refers to the same option — skip the language and fall back to base-only matching
        // (translated answers surface as "Other", the safe pre-fix behavior) rather than risk
        // folding a response into the wrong choice.
        if (!translatedChoices || translatedChoices.length !== baseChoices.length) {
            continue
        }
        translatedChoices.forEach((choice, index) => {
            const baseChoice = baseChoices[index]
            if (choice && baseChoice !== undefined) {
                map.set(choice, baseChoice)
            }
        })
    }

    // Seed base choices last so they take precedence: a translation that reuses another
    // base-choice string must not remap that base choice to a different option. The tradeoff is
    // lossy — a translated pick that collides with a different base choice is attributed to that
    // base option — but it's the safe default (base-language data is never misattributed).
    baseChoices.forEach((choice) => map.set(choice, choice))

    return map
}

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
    if (translation.submitButtonText) {
        appearanceUpdates.submitButtonText = translation.submitButtonText
    }
    if (translation.backButtonText) {
        appearanceUpdates.backButtonText = translation.backButtonText
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
