import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    Survey,
    SurveyQuestionDescriptionContentType,
    SurveyQuestionType,
    SurveySchedule,
    SurveyType,
} from '~/types'

import { SURVEY_CREATED_SOURCE, SURVEY_RATING_SCALE, SurveyTemplate, SurveyTemplateType } from '../constants'
import { surveyWizardLogic } from './surveyWizardLogic'

const createMockTemplate = (): SurveyTemplate => ({
    templateType: SurveyTemplateType.NPS,
    questions: [
        {
            type: SurveyQuestionType.Rating,
            question: 'How likely are you to recommend us?',
            description: '',
            descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
            display: 'number',
            scale: SURVEY_RATING_SCALE.NPS_10_POINT,
            lowerBoundLabel: 'Not likely',
            upperBoundLabel: 'Very likely',
        },
    ],
    description: 'NPS survey',
    type: SurveyType.Popover,
})

const createMockSurvey = (): Survey => ({
    id: 'test-survey',
    name: 'Test Survey',
    description: '',
    type: SurveyType.Popover,
    linked_flag_id: null,
    linked_flag: null,
    targeting_flag: null,
    questions: [
        {
            type: SurveyQuestionType.Open,
            question: 'What do you think?',
        },
    ],
    conditions: null,
    appearance: null,
    created_at: '2024-01-01T00:00:00Z',
    created_by: null,
    start_date: null,
    end_date: null,
    archived: false,
    targeting_flag_filters: undefined,
    responses_limit: null,
    iteration_count: null,
    iteration_frequency_days: null,
    schedule: SurveySchedule.Once,
    user_access_level: AccessControlLevel.Editor,
})

describe('surveyWizardLogic', () => {
    describe('product intent tracking for survey creation', () => {
        let capturedIntentRequests: any[]

        beforeEach(() => {
            initKeaTests()
            capturedIntentRequests = []

            useMocks({
                get: {
                    '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                    '/api/projects/:team/surveys/responses_count': () => [200, {}],
                },
                post: {
                    '/api/projects/:team/surveys/': () => {
                        const mockSurvey = createMockSurvey()
                        return [200, { ...mockSurvey, id: 'new-survey-123', start_date: new Date().toISOString() }]
                    },
                },
                patch: {
                    '/api/environments/@current/add_product_intent/': async (req) => {
                        const data = await req.json()
                        capturedIntentRequests.push(data)
                        return [200, {}]
                    },
                },
            })
        })

        afterEach(() => {
            capturedIntentRequests = []
        })

        it('should track SURVEY_CREATED and SURVEY_LAUNCHED intents when launching survey', async () => {
            const logic = surveyWizardLogic({ id: 'new' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.selectTemplate(createMockTemplate())
                logic.actions.launchSurvey()
            }).toFinishAllListeners()

            const createdIntent = capturedIntentRequests.find(
                (req) => req.intent_context === ProductIntentContext.SURVEY_CREATED
            )
            expect(createdIntent).toBeTruthy()
            expect(createdIntent).toMatchObject({
                product_type: ProductKey.SURVEYS,
                intent_context: ProductIntentContext.SURVEY_CREATED,
                metadata: {
                    survey_id: 'new-survey-123',
                    source: SURVEY_CREATED_SOURCE.SURVEY_WIZARD,
                },
            })

            const launchedIntent = capturedIntentRequests.find(
                (req) => req.intent_context === ProductIntentContext.SURVEY_LAUNCHED
            )
            expect(launchedIntent).toBeTruthy()
            expect(launchedIntent).toMatchObject({
                product_type: ProductKey.SURVEYS,
                intent_context: ProductIntentContext.SURVEY_LAUNCHED,
                metadata: {
                    survey_id: 'new-survey-123',
                    source: SURVEY_CREATED_SOURCE.SURVEY_WIZARD,
                },
            })
        })

        it('should track SURVEY_CREATED intent when saving draft', async () => {
            useMocks({
                post: {
                    '/api/projects/:team/surveys/': () => {
                        const mockSurvey = createMockSurvey()
                        return [200, { ...mockSurvey, id: 'draft-survey-123', start_date: null }]
                    },
                },
            })

            const logic = surveyWizardLogic({ id: 'new' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.selectTemplate(createMockTemplate())
                logic.actions.saveDraft()
            }).toFinishAllListeners()

            const createdIntent = capturedIntentRequests.find(
                (req) => req.intent_context === ProductIntentContext.SURVEY_CREATED
            )
            expect(createdIntent).toBeTruthy()
            expect(createdIntent).toMatchObject({
                product_type: ProductKey.SURVEYS,
                intent_context: ProductIntentContext.SURVEY_CREATED,
                metadata: {
                    survey_id: 'draft-survey-123',
                    source: SURVEY_CREATED_SOURCE.SURVEY_WIZARD,
                },
            })

            // Draft should NOT track SURVEY_LAUNCHED
            const launchedIntent = capturedIntentRequests.find(
                (req) => req.intent_context === ProductIntentContext.SURVEY_LAUNCHED
            )
            expect(launchedIntent).toBeUndefined()
        })
    })

    describe('wizard step navigation', () => {
        beforeEach(() => {
            initKeaTests()

            useMocks({
                get: {
                    '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                    '/api/projects/:team/surveys/responses_count': () => [200, {}],
                },
                patch: {
                    '/api/environments/@current/add_product_intent/': () => [200, {}],
                },
            })
        })

        it('should start at template step for new survey', () => {
            const logic = surveyWizardLogic({ id: 'new' })
            logic.mount()

            expect(logic.values.currentStep).toBe('template')
        })

        it('should move to questions step after selecting template', async () => {
            const logic = surveyWizardLogic({ id: 'new' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.selectTemplate(createMockTemplate())
            }).toMatchValues({
                currentStep: 'questions',
                selectedTemplate: expect.objectContaining({
                    templateType: 'Net promoter score (NPS)',
                }),
            })
        })

        it('should track step progression through wizard', async () => {
            const logic = surveyWizardLogic({ id: 'new' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.selectTemplate(createMockTemplate())
            }).toMatchValues({
                currentStep: 'questions',
            })

            await expectLogic(logic, () => {
                logic.actions.nextStep()
            }).toMatchValues({
                currentStep: 'where',
            })

            await expectLogic(logic, () => {
                logic.actions.nextStep()
            }).toMatchValues({
                currentStep: 'when',
            })
        })
    })

    describe('template selection', () => {
        beforeEach(() => {
            initKeaTests()

            useMocks({
                get: {
                    '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                    '/api/projects/:team/surveys/responses_count': () => [200, {}],
                },
                patch: {
                    '/api/environments/@current/add_product_intent/': () => [200, {}],
                },
            })
        })

        it('should populate survey fields when template is selected', async () => {
            const logic = surveyWizardLogic({ id: 'new' })
            logic.mount()

            const template = createMockTemplate()

            await expectLogic(logic, () => {
                logic.actions.selectTemplate(template)
            }).toMatchValues({
                survey: expect.objectContaining({
                    name: expect.stringContaining('Net promoter score (NPS)'),
                    description: template.description,
                    type: template.type,
                    questions: template.questions,
                }),
            })
        })

        it('should apply recommended frequency based on template type', async () => {
            const logic = surveyWizardLogic({ id: 'new' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.selectTemplate(createMockTemplate())
            }).toMatchValues({
                recommendedFrequency: expect.objectContaining({
                    value: 'quarterly',
                    reason: 'Relationship metrics work best quarterly',
                }),
            })
        })
    })
})
