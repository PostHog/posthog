import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, Survey, SurveyPosition, SurveyQuestionType, SurveySchedule, SurveyType } from '~/types'

import { surveyLogic } from '../../surveyLogic'
import { WhenStep } from './WhenStep'

jest.mock('lib/components/PropertyFilters/PropertyFilters', () => ({
    PropertyFilters: () => <div data-testid="property-filters" />,
}))

const createEventTriggeredSurvey = (repeatedActivation: boolean): Survey => ({
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
    conditions: {
        actions: null,
        events: { values: [{ name: 'payment_completed' }], repeatedActivation },
    },
    appearance: {
        position: SurveyPosition.Right,
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

const surveyMocks = (survey: Survey): Parameters<typeof useMocks>[0] => ({
    get: {
        '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
        '/api/projects/:team/surveys/test-survey/': () => [200, survey],
        '/api/projects/:team/surveys/responses_count': () => [200, {}],
    },
})

describe('WhenStep', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    const renderWhenStep = (): void => {
        render(
            <Provider>
                <BindLogic logic={surveyLogic} props={{ id: 'test-survey' }}>
                    <WhenStep />
                </BindLogic>
            </Provider>
        )
    }

    it('replaces the schedule options with an explanation when the survey shows on every event capture', async () => {
        useMocks(surveyMocks(createEventTriggeredSurvey(true)))
        renderWhenStep()

        expect(await screen.findByText(/the schedule options don't apply/)).toBeInTheDocument()
        expect(screen.queryByText('Once ever')).not.toBeInTheDocument()
        // The wait period and response limit still apply at runtime, so they stay configurable
        expect(
            screen.getByText("Don't show this survey if another one was shown to the user in the last")
        ).toBeInTheDocument()
        expect(screen.getByText('Stop after')).toBeInTheDocument()
    })

    it('keeps the schedule options for event-triggered surveys that show once per user', async () => {
        useMocks(surveyMocks(createEventTriggeredSurvey(false)))
        renderWhenStep()

        expect(await screen.findByText('payment_completed')).toBeInTheDocument()
        expect(screen.getByText('Once ever')).toBeInTheDocument()
        expect(screen.queryByText(/the schedule options don't apply/)).not.toBeInTheDocument()
    })
})
