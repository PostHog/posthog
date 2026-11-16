import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { Survey, SurveyType } from '~/types'

import { DEFAULT_FEEDBACK_SURVEY_NAME } from './feedbackSurvey'
import { feedbackSurveyModalLogic } from './feedbackSurveyModalLogic'

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    lemonToast: {
        error: jest.fn(),
        success: jest.fn(),
    },
}))
jest.mock('lib/utils/product-intents', () => ({
    addProductIntent: jest.fn(() => Promise.resolve(null)),
}))

describe('feedbackSurveyModalLogic', () => {
    let logic: ReturnType<typeof feedbackSurveyModalLogic.build>
    let createSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        createSpy = jest.spyOn(api.surveys, 'create')
        logic = feedbackSurveyModalLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        createSpy.mockRestore()
    })

    it('opens with defaults and the follow-up turned on', async () => {
        await expectLogic(logic, () => logic.actions.openModal()).toMatchValues({
            isOpen: true,
            createdSurvey: null,
            feedbackSurvey: expect.objectContaining({
                name: DEFAULT_FEEDBACK_SURVEY_NAME,
                followUpEnabled: true,
            }),
        })
    })

    it('creates an API survey and keeps it for the setup step', async () => {
        const survey = { id: 'survey-1', name: DEFAULT_FEEDBACK_SURVEY_NAME } as Survey
        createSpy.mockResolvedValue(survey)

        logic.actions.openModal()
        await expectLogic(logic, () => logic.actions.submitFeedbackSurvey())
            .toFinishAllListeners()
            .toMatchValues({ createdSurvey: survey, isOpen: true })

        expect(createSpy).toHaveBeenCalledWith(expect.objectContaining({ type: SurveyType.API }))
        expect(lemonToast.success).toHaveBeenCalled()
    })

    it('does not call the API when the follow-up question is empty', async () => {
        logic.actions.openModal()
        logic.actions.setFeedbackSurveyValue('followUpQuestion', '')

        await expectLogic(logic, () => logic.actions.submitFeedbackSurvey())
            .toFinishAllListeners()
            .toMatchValues({ createdSurvey: null })

        expect(createSpy).not.toHaveBeenCalled()
    })

    it('shows an error and stays on the form when creation fails', async () => {
        createSpy.mockRejectedValue({ detail: 'Nope' })

        logic.actions.openModal()
        await expectLogic(logic, () => logic.actions.submitFeedbackSurvey())
            .toFinishAllListeners()
            .toMatchValues({ createdSurvey: null })

        expect(lemonToast.error).toHaveBeenCalledWith('Nope')
    })
})
