import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'
import { router } from 'kea-router'

import { SurveyQuestionVisualization } from 'scenes/surveys/components/question-visualizations/SurveyQuestionVisualization'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { LinkSurveyQuestion, SurveyQuestionType } from '~/types'

const LINK_QUESTION: LinkSurveyQuestion = {
    id: 'q-link',
    type: SurveyQuestionType.Link,
    question: 'Read the release notes',
    link: 'https://example.com/release-notes',
}

describe('SurveyQuestionVisualization', () => {
    afterEach(() => {
        cleanup()
    })

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
        router.actions.push('/surveys/test-survey')
        useMocks({
            get: {
                '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                '/api/projects/:team/surveys/test-survey/': () => [
                    200,
                    {
                        id: 'test-survey',
                        name: 'Test survey',
                        type: 'popover',
                        questions: [LINK_QUESTION],
                        start_date: '2026-01-01T00:00:00Z',
                        end_date: null,
                        archived: false,
                        appearance: {},
                        conditions: null,
                        created_at: '2026-01-01T00:00:00Z',
                    },
                ],
                '/api/projects/:team/surveys/test-survey/archived-response-uuids/': () => [200, []],
                '/api/projects/:team/surveys/responses_count/': () => [200, {}],
            },
            post: {
                '/api/environments/:team_id/query/': () => [200, { results: [] }],
            },
        })
        surveyLogic({ id: 'test-survey' }).mount()
    })

    it('explains that a link question holds no answers instead of rendering nothing', () => {
        render(
            <BindLogic logic={surveyLogic} props={{ id: 'test-survey' }}>
                <SurveyQuestionVisualization question={LINK_QUESTION} questionIndex={1} />
            </BindLogic>
        )

        expect(screen.getByText(/Question 2: Read the release notes/)).toBeTruthy()
        expect(screen.getByText(/Link questions don't collect answers/)).toBeTruthy()
        expect(screen.queryByText('Copy response key')).toBeNull()
    })
})
