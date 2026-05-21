import {
    AccessControlLevel,
    MultipleSurveyQuestion,
    RatingSurveyQuestion,
    Survey,
    SurveyPosition,
    SurveyQuestionType,
    SurveySchedule,
    SurveyType,
} from '~/types'

import { getSurveyWithTranslatedContent } from './surveyTranslationUtils'

const createSurvey = (): Survey => ({
    id: 'test-survey',
    name: 'Customer feedback',
    description: '',
    type: SurveyType.Popover,
    linked_flag: null,
    linked_flag_id: null,
    targeting_flag: null,
    questions: [
        {
            type: SurveyQuestionType.SingleChoice,
            question: 'How was onboarding?',
            description: 'Pick the closest answer',
            choices: ['Great', 'Okay'],
            translations: {
                fr: {
                    question: "Comment s'est passee l'integration ?",
                    description: 'Choisissez la reponse la plus proche',
                    choices: ['Super', 'Correct'],
                },
            },
        },
        {
            type: SurveyQuestionType.Rating,
            question: 'How likely are you to recommend us?',
            display: 'number',
            scale: 10,
            lowerBoundLabel: 'Unlikely',
            upperBoundLabel: 'Very likely',
            translations: {
                fr: {
                    question: 'Quelle est la probabilite de nous recommander ?',
                    lowerBoundLabel: 'Peu probable',
                    upperBoundLabel: 'Tres probable',
                },
            },
        },
    ],
    conditions: null,
    appearance: {
        position: SurveyPosition.Right,
        displayThankYouMessage: true,
        thankYouMessageHeader: 'Thank you',
        thankYouMessageDescription: 'We appreciate your feedback.',
    },
    translations: {
        fr: {
            name: 'Avis client',
            thankYouMessageHeader: 'Merci',
            thankYouMessageDescription: 'Merci pour votre retour.',
        },
    },
    created_at: '2026-01-01T00:00:00.000Z',
    created_by: null,
    start_date: null,
    end_date: null,
    archived: false,
    targeting_flag_filters: undefined,
    responses_limit: null,
    schedule: SurveySchedule.Once,
    user_access_level: AccessControlLevel.Editor,
})

describe('getSurveyWithTranslatedContent', () => {
    it('applies survey, question, choice, and appearance translations for previews', () => {
        const survey = createSurvey()

        const translatedSurvey = getSurveyWithTranslatedContent(survey, 'fr')
        const translatedChoiceQuestion = translatedSurvey.questions[0] as MultipleSurveyQuestion
        const translatedRatingQuestion = translatedSurvey.questions[1] as RatingSurveyQuestion

        expect(translatedSurvey.name).toBe('Avis client')
        expect(translatedSurvey.appearance?.thankYouMessageHeader).toBe('Merci')
        expect(translatedSurvey.appearance?.thankYouMessageDescription).toBe('Merci pour votre retour.')
        expect(translatedChoiceQuestion.question).toBe("Comment s'est passee l'integration ?")
        expect(translatedChoiceQuestion.description).toBe('Choisissez la reponse la plus proche')
        expect(translatedChoiceQuestion.choices).toEqual(['Super', 'Correct'])
        expect(translatedRatingQuestion.question).toBe('Quelle est la probabilite de nous recommander ?')
        expect(translatedRatingQuestion.lowerBoundLabel).toBe('Peu probable')
        expect(translatedRatingQuestion.upperBoundLabel).toBe('Tres probable')
        expect(survey.questions[0].question).toBe('How was onboarding?')
    })

    it('returns the original survey when the language has no root translation', () => {
        const survey = createSurvey()

        expect(getSurveyWithTranslatedContent(survey, 'es')).toBe(survey)
        expect(getSurveyWithTranslatedContent(survey, null)).toBe(survey)
    })
})
