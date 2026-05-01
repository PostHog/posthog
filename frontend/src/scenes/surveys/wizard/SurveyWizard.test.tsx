import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, Survey, SurveyPosition, SurveyQuestionType, SurveySchedule, SurveyType } from '~/types'

import { SurveyWizardComponent } from './SurveyWizard'

const createGuidedSurvey = (): Survey => ({
    id: 'test-survey',
    name: 'Test survey',
    description: '',
    type: SurveyType.Popover,
    linked_flag: null,
    linked_flag_id: null,
    targeting_flag: null,
    questions: [
        {
            type: SurveyQuestionType.Open,
            question: 'What do you think?',
            description: '',
            buttonText: 'Submit',
        },
    ],
    conditions: null,
    appearance: {
        position: SurveyPosition.Right,
        displayThankYouMessage: true,
        thankYouMessageHeader: 'Thank you',
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

describe('SurveyWizard', () => {
    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        localStorage.setItem('scenes.surveys.surveysLogic.preferredEditor', JSON.stringify('full'))

        useMocks({
            get: {
                '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                '/api/projects/:team/surveys/test-survey/': () => [200, createGuidedSurvey()],
                '/api/projects/:team/surveys/responses_count': () => [200, {}],
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': () => [200, {}],
            },
        })

        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        featureFlagLogic.unmount()
        jest.restoreAllMocks()
    })

    it('keeps new surveys on template selection when full editor is preferred', async () => {
        router.actions.push('/surveys/guided/new')

        const replaceSpy = jest.spyOn(router.actions, 'replace').mockImplementation(() => {})

        render(<SurveyWizardComponent id="new" />)

        expect(await screen.findByText('Choose a survey template')).toBeInTheDocument()

        expect(replaceSpy).not.toHaveBeenCalled()
    })

    it('shows the translations section in the guided form when the feature flag is enabled', async () => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SURVEYS_TRANSLATIONS], {
            [FEATURE_FLAGS.SURVEYS_TRANSLATIONS]: true,
        })
        router.actions.push('/surveys/guided/test-survey')

        render(<SurveyWizardComponent id="test-survey" />)

        expect(await screen.findByText('Translations')).toBeInTheDocument()
        expect(screen.getByPlaceholderText('Add a language')).toBeInTheDocument()
    })
})
