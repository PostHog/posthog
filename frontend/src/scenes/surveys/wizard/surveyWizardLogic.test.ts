import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

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
import { surveyLogic } from '../surveyLogic'
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
                    '/api/environments/:team_id/add_product_intent/': async ({ request }) => {
                        const data = await request.json()
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
                    '/api/environments/:team_id/add_product_intent/': () => [200, {}],
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

        it('preserves unsaved full editor changes when switching to the guided editor', async () => {
            const surveyFormLogic = surveyLogic({ id: 'new' })
            surveyFormLogic.mount()

            await expectLogic(surveyFormLogic, () => {
                surveyFormLogic.actions.setSurveyValue('description', 'Edited in the full editor')
            }).toMatchValues({
                surveyChanged: true,
            })

            router.actions.push('/surveys/guided/new')

            const logic = surveyWizardLogic({ id: 'new' })
            logic.mount()

            expect(logic.values.currentStep).toBe('questions')
            expect(logic.values.survey.description).toBe('Edited in the full editor')
        })

        it('preserves unsaved guided editor changes when switching to the full editor', async () => {
            // surveyLogic is normally mounted by the destination Survey scene; mount it
            // separately so the wizard logic's connect doesn't tear it down on unmount.
            const surveyFormLogic = surveyLogic({ id: 'new' })
            surveyFormLogic.mount()

            const wizardLogic = surveyWizardLogic({ id: 'new' })
            const unmountWizard = wizardLogic.mount()

            await expectLogic(wizardLogic, () => {
                wizardLogic.actions.setSurveyValue('description', 'Edited in the guided editor')
            }).toMatchValues({
                surveyChanged: true,
            })

            router.actions.push('/surveys/new')
            unmountWizard()

            expect(surveyFormLogic.values.survey.description).toBe('Edited in the guided editor')
            expect(surveyFormLogic.values.surveyChanged).toBe(true)
        })

        it('resets new survey state when navigating away from the survey editor', async () => {
            const surveyFormLogic = surveyLogic({ id: 'new' })
            surveyFormLogic.mount()

            const wizardLogic = surveyWizardLogic({ id: 'new' })
            const unmountWizard = wizardLogic.mount()

            await expectLogic(wizardLogic, () => {
                wizardLogic.actions.setSurveyValue('description', 'Discarded edit')
            }).toMatchValues({
                surveyChanged: true,
            })

            router.actions.push('/surveys')
            unmountWizard()

            expect(surveyFormLogic.values.survey.description).toBe('')
        })

        it('preserves the in-memory draft when switching to the full editor without any URL flag', async () => {
            // Regression test: previously the wizard had to push `#preserveLocalChanges=true`
            // to keep state across editor swaps. Verify the flag-free path works.
            const surveyFormLogic = surveyLogic({ id: 'new' })
            surveyFormLogic.mount()

            const wizardLogic = surveyWizardLogic({ id: 'new' })
            const unmountWizard = wizardLogic.mount()

            await expectLogic(wizardLogic, () => {
                wizardLogic.actions.setSurveyValue('name', 'Drafted in the wizard')
            }).toMatchValues({
                surveyChanged: true,
            })

            router.actions.push(urls.survey('new'))
            unmountWizard()

            expect(surveyFormLogic.values.survey.name).toBe('Drafted in the wizard')
            expect(surveyFormLogic.values.surveyChanged).toBe(true)
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
                    '/api/environments/:team_id/add_product_intent/': () => [200, {}],
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

        it.each([
            {
                mode: 'in_app' as const,
                expectedCore: [
                    SurveyTemplateType.NPS,
                    SurveyTemplateType.CSAT,
                    SurveyTemplateType.PMF,
                    SurveyTemplateType.OpenFeedback,
                ],
                otherContains: [SurveyTemplateType.Announcement, SurveyTemplateType.ErrorTracking],
                otherExcludes: [SurveyTemplateType.UserResearchIntake, SurveyTemplateType.ProductResearch],
            },
            {
                mode: 'hosted' as const,
                expectedCore: [
                    SurveyTemplateType.UserResearchIntake,
                    SurveyTemplateType.ProductResearch,
                    SurveyTemplateType.NPS,
                    SurveyTemplateType.CCR,
                ],
                otherContains: [SurveyTemplateType.FeatureRequest],
                otherExcludes: [
                    SurveyTemplateType.Announcement,
                    SurveyTemplateType.ErrorTracking,
                    SurveyTemplateType.OnboardingFeedback,
                ],
            },
        ])('exposes mode-specific templates for $mode mode', ({ mode, expectedCore, otherContains, otherExcludes }) => {
            const logic = surveyWizardLogic({ id: 'new' })
            logic.mount()
            logic.actions.setTemplateMode(mode)

            const coreTypes = logic.values.coreTemplates.map((t) => t.templateType)
            expect(coreTypes).toEqual(expectedCore)

            const otherTypes = logic.values.otherTemplates.map((t) => t.templateType)
            otherContains.forEach((type) => expect(otherTypes).toContain(type))
            otherExcludes.forEach((type) => expect(otherTypes).not.toContain(type))
        })
    })
})
