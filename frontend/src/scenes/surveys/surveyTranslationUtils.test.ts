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

import { buildChoiceTranslationMap, getSurveyWithTranslatedContent } from './surveyTranslationUtils'

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

    it('applies submit and back button label translations to the appearance', () => {
        const survey = createSurvey()
        survey.appearance = {
            ...survey.appearance,
            submitButtonText: 'Submit',
            allowGoBack: true,
            backButtonText: 'Back',
        }
        survey.translations = {
            fr: {
                ...survey.translations?.fr,
                submitButtonText: 'Envoyer',
                backButtonText: 'Retour',
            },
        }

        const translatedSurvey = getSurveyWithTranslatedContent(survey, 'fr')

        expect(translatedSurvey.appearance?.submitButtonText).toBe('Envoyer')
        expect(translatedSurvey.appearance?.backButtonText).toBe('Retour')
    })

    it('returns the original survey when the language has no root translation', () => {
        const survey = createSurvey()

        expect(getSurveyWithTranslatedContent(survey, 'es')).toBe(survey)
        expect(getSurveyWithTranslatedContent(survey, null)).toBe(survey)
    })
})

describe('buildChoiceTranslationMap', () => {
    const baseQuestion = (overrides: Partial<MultipleSurveyQuestion> = {}): MultipleSurveyQuestion => ({
        type: SurveyQuestionType.SingleChoice,
        question: 'Pick one',
        choices: ['yes', 'no'],
        ...overrides,
    })

    it.each([
        [
            'maps each translation back to its base choice',
            baseQuestion({ translations: { 'zh-cn': { choices: ['是', '否'] } } }),
            { 是: 'yes', 否: 'no', yes: 'yes', no: 'no' },
        ],
        [
            'merges multiple languages',
            baseQuestion({
                translations: { 'zh-cn': { choices: ['是', '否'] }, fr: { choices: ['oui', 'non'] } },
            }),
            { 是: 'yes', 否: 'no', oui: 'yes', non: 'no', yes: 'yes', no: 'no' },
        ],
        [
            'keeps base choices winning over a translation reusing another base choice',
            baseQuestion({ translations: { fr: { choices: ['oui', 'yes'] } } }),
            { oui: 'yes', yes: 'yes', no: 'no' },
        ],
        [
            'skips a translation whose choices array length is out of sync',
            baseQuestion({ choices: ['yes', 'no', 'maybe'], translations: { fr: { choices: ['oui', 'non'] } } }),
            { yes: 'yes', no: 'no', maybe: 'maybe' },
        ],
        [
            'never maps the "[Translation needed]" placeholder',
            baseQuestion({ translations: { fr: { choices: ['[Translation needed]', 'non'] } } }),
            { non: 'no', yes: 'yes', no: 'no' },
        ],
        [
            'never maps an empty or whitespace-only translated choice',
            baseQuestion({ translations: { fr: { choices: ['', '   '] } } }),
            { yes: 'yes', no: 'no' },
        ],
        [
            // By far the common case — an untranslated choice question must still map its own
            // choices, otherwise every answer gets treated as free-text "Other".
            'seeds base choices for a question with no translations',
            baseQuestion(),
            { yes: 'yes', no: 'no' },
        ],
        [
            'seeds base choices when translations is null',
            baseQuestion({ translations: null }),
            { yes: 'yes', no: 'no' },
        ],
        ['returns only an empty map for a question with no choices', baseQuestion({ choices: [] }), {}],
    ])('%s', (_name, question, expected) => {
        expect(buildChoiceTranslationMap(question)).toEqual(new Map(Object.entries(expected)))
    })
})
