import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, Survey, SurveyAppearance, SurveyQuestionType, SurveySchedule, SurveyType } from '~/types'

import { HostedSurveySettingsPanel } from './HostedSurveySettingsPanel'

const buildSurvey = (appearance: SurveyAppearance): Survey => ({
    id: 'test-survey',
    name: 'Test survey',
    description: '',
    type: SurveyType.ExternalSurvey,
    linked_flag: null,
    linked_flag_id: null,
    targeting_flag: null,
    questions: [{ type: SurveyQuestionType.Open, question: 'What do you think?', description: '' }],
    conditions: null,
    appearance,
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

describe('HostedSurveySettingsPanel', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                '/api/projects/:team/surveys/test-survey/': () => [200, buildSurvey({})],
                '/api/projects/:team/surveys/responses_count': () => [200, {}],
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    it.each([
        ['an intro with no content', 'intro', { displayIntroScreen: true }, true],
        ['an intro with a header', 'intro', { displayIntroScreen: true, introScreenHeader: 'Welcome' }, false],
        ['the confirmation page', 'confirmation', { displayIntroScreen: true }, false],
    ] as const)('warns that the intro will not show for %s', (_name, pageKind, appearance, warns) => {
        const survey = buildSurvey(appearance)
        const logic = surveyLogic({ id: survey.id })
        logic.mount()
        logic.actions.loadSurveySuccess(survey)

        render(
            <BindLogic logic={surveyLogic} props={{ id: survey.id }}>
                <HostedSurveySettingsPanel
                    activePageIndex={pageKind === 'intro' ? -1 : 1}
                    pageKind={pageKind}
                    viewport="desktop"
                    onViewportChange={jest.fn()}
                    onRemoveIntro={jest.fn()}
                    onRemoveConfirmation={jest.fn()}
                />
            </BindLogic>
        )

        const warning = screen.queryByText("The intro screen won't show until it has a header or a description.")
        expect(!!warning).toBe(warns)
    })
})
