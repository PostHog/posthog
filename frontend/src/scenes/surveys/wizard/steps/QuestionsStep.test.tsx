import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    RatingSurveyQuestion,
    Survey,
    SurveyPosition,
    SurveyQuestionType,
    SurveySchedule,
    SurveyType,
} from '~/types'

import { surveyLogic } from '../../surveyLogic'
import { surveyWizardLogic } from '../surveyWizardLogic'
import { QuestionsStep } from './QuestionsStep'

const createRatingSurvey = (question: Partial<RatingSurveyQuestion>): Survey =>
    ({
        id: 'test-survey',
        name: 'Test survey',
        description: '',
        type: SurveyType.Popover,
        linked_flag: null,
        linked_flag_id: null,
        targeting_flag: null,
        questions: [
            {
                type: SurveyQuestionType.Rating,
                question: 'How likely are you to recommend us?',
                description: '',
                display: 'number',
                scale: 5,
                lowerBoundLabel: 'Unlikely',
                upperBoundLabel: 'Very likely',
                ...question,
            },
        ],
        conditions: null,
        appearance: { position: SurveyPosition.Right },
        created_at: '2026-01-01T00:00:00.000Z',
        created_by: null,
        start_date: null,
        end_date: null,
        archived: false,
        targeting_flag_filters: undefined,
        responses_limit: null,
        schedule: SurveySchedule.Once,
        user_access_level: AccessControlLevel.Editor,
    }) as Survey

const surveyMocks = (survey: Survey): Parameters<typeof useMocks>[0] => ({
    get: {
        '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
        '/api/projects/:team/surveys/test-survey/': () => [200, survey],
        '/api/projects/:team/surveys/responses_count': () => [200, {}],
    },
})

describe('QuestionsStep', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    const renderQuestionsStep = (): void => {
        render(
            <Provider>
                <BindLogic logic={surveyLogic} props={{ id: 'test-survey' }}>
                    <BindLogic logic={surveyWizardLogic} props={{ id: 'test-survey' }}>
                        <QuestionsStep editingLanguage={null} setEditingLanguage={() => {}} />
                    </BindLogic>
                </BindLogic>
            </Provider>
        )
    }

    const scaleButton = (label: string): HTMLElement => screen.getByText(label).closest('button') as HTMLElement

    it('keeps the selected scale when the display type does not change', async () => {
        useMocks(surveyMocks(createRatingSurvey({ scale: 7 })))
        renderQuestionsStep()

        expect(await screen.findByTitle('Numbers')).toBeInTheDocument()
        expect(scaleButton('1-7')).toHaveAttribute('aria-pressed', 'true')

        await userEvent.click(screen.getByTitle('Numbers'))

        expect(scaleButton('1-7')).toHaveAttribute('aria-pressed', 'true')
    })

    it('falls back to a supported scale when the display type changes', async () => {
        useMocks(surveyMocks(createRatingSurvey({ display: 'emoji', scale: 2 })))
        renderQuestionsStep()

        expect(await screen.findByTitle('Numbers')).toBeInTheDocument()
        expect(scaleButton('Thumbs')).toHaveAttribute('aria-pressed', 'true')

        await userEvent.click(screen.getByTitle('Numbers'))

        expect(scaleButton('1-5')).toHaveAttribute('aria-pressed', 'true')
    })
})
