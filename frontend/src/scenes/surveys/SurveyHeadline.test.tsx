import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'
import { router } from 'kea-router'

import { SurveyHeadline } from 'scenes/surveys/SurveyHeadline'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

const HEADLINE_SUMMARY = 'People want a faster upload.'

describe('SurveyHeadline', () => {
    let logic: ReturnType<typeof surveyLogic.build>

    afterEach(() => {
        cleanup()
        logic?.unmount()
    })

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                '/api/projects/:team/surveys/test-survey/': () => [
                    200,
                    {
                        id: 'test-survey',
                        name: 'Test survey',
                        type: 'popover',
                        questions: [{ id: 'q1', type: 'open', question: 'What can we improve?' }],
                        start_date: '2026-01-01T00:00:00Z',
                        end_date: null,
                        archived: false,
                        appearance: {},
                        conditions: null,
                        created_at: '2026-01-01T00:00:00Z',
                        headline_summary: HEADLINE_SUMMARY,
                        headline_response_count: 23,
                    },
                ],
                '/api/projects/:team/surveys/test-survey/archived-response-uuids/': () => [200, []],
                '/api/projects/:team/surveys/responses_count/': () => [200, {}],
            },
            post: {
                '/api/environments/:team_id/query/': () => [200, { results: [] }],
            },
        })
    })

    function renderHeadline(aiDataProcessingApproved: boolean): HTMLElement {
        initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: aiDataProcessingApproved,
        })
        router.actions.push('/surveys/test-survey')
        logic = surveyLogic({ id: 'test-survey' })
        logic.mount()

        const { container } = render(
            <BindLogic logic={surveyLogic} props={{ id: 'test-survey' }}>
                <SurveyHeadline />
            </BindLogic>
        )
        return container
    }

    it('shows a stored summary when the organization approved AI data processing', async () => {
        renderHeadline(true)

        expect(await screen.findByText(HEADLINE_SUMMARY)).toBeTruthy()
    })

    it('hides a stored summary when the organization did not approve AI data processing', async () => {
        const container = renderHeadline(false)

        // The summary must reach the logic first, so that the empty render proves the gate and
        // not a survey that is still on its way.
        await waitFor(() => expect(logic.values.survey.headline_summary).toBe(HEADLINE_SUMMARY))

        expect(container.firstChild).toBeNull()
        expect(screen.queryByText(HEADLINE_SUMMARY)).toBeNull()
    })
})
