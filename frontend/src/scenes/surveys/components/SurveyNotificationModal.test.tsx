import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { surveyNotificationModalLogic } from 'scenes/surveys/surveyNotificationModalLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Survey, SurveyQuestionType, SurveySchedule, SurveyType } from '~/types'

import { SurveyNotificationModal } from './SurveyNotificationModal'

jest.mock('lib/monaco/CodeEditorResizable', () => ({
    CodeEditorResizeable: () => <div data-testid="template-editor" />,
}))
jest.mock('lib/components/CyclotronJob/integrations/IntegrationChoice', () => ({
    IntegrationChoice: () => null,
}))

const SURVEY_ID = 'survey-under-test'

function buildSurvey(type: SurveyType): Survey {
    return {
        id: SURVEY_ID,
        name: 'Beta exit',
        type,
        schedule: SurveySchedule.Once,
        questions: [{ id: 'q1', question: 'Why are you leaving?', type: SurveyQuestionType.Open }],
        enable_partial_responses: true,
        conditions: null,
        appearance: null,
        created_at: '2026-01-01T00:00:00Z',
        archived: false,
    } as unknown as Survey
}

function renderModalForSurveyType(type: SurveyType): void {
    const survey = surveyLogic({ id: SURVEY_ID })
    survey.mount()
    survey.actions.loadSurveySuccess(buildSurvey(type))

    const modal = surveyNotificationModalLogic({ surveyId: SURVEY_ID })
    modal.mount()
    modal.actions.openDialog()

    render(<SurveyNotificationModal surveyId={SURVEY_ID} />)
}

describe('SurveyNotificationModal', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/hog_functions/': { results: [] },
                '/api/environments/:team_id/hog_functions/': { results: [] },
                '/api/projects/:team_id/integrations': { results: [] },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    // An API survey's events come from the customer's own code, so PostHog cannot infer completion.
    // Without this guidance the only symptom of a missing $survey_completed is a notification that
    // silently never fires.
    it('tells API surveys their events need the completion property', () => {
        renderModalForSurveyType(SurveyType.API)

        expect(screen.getByText(/\$survey_completed: true/)).toBeInTheDocument()
    })

    it('leaves the guidance out for surveys PostHog renders itself', () => {
        renderModalForSurveyType(SurveyType.Popover)

        expect(screen.queryByText(/\$survey_completed: true/)).not.toBeInTheDocument()
    })
})
