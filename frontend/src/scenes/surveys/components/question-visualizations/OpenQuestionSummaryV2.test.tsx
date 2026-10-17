import { act, cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'
import { router } from 'kea-router'

import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { OpenQuestionSummaryV2 } from 'scenes/surveys/components/question-visualizations/OpenQuestionSummaryV2'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

jest.mock('@posthog/react/surveys', () => ({
    useThumbSurvey: () => ({ respond: jest.fn(), response: null, triggerRef: { current: null } }),
}))

const SUMMARY_CONTENT = 'Responses ask for faster uploads.'

describe('OpenQuestionSummaryV2', () => {
    let logic: ReturnType<typeof surveyLogic.build>
    let summarizeRequests: number

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
        logic?.unmount()
        maxGlobalLogic.findMounted()?.unmount()
    })

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
        router.actions.push('/surveys/test-survey')
        summarizeRequests = 0
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
                    },
                ],
                '/api/projects/:team/surveys/test-survey/archived-response-uuids/': () => [200, []],
                '/api/projects/:team/surveys/responses_count/': () => [200, {}],
            },
            post: {
                '/api/environments/:team_id/query/': () => [200, { results: [] }],
                '/api/projects/:team/surveys/test-survey/summarize_responses/': () => {
                    summarizeRequests += 1
                    return [
                        200,
                        {
                            content: SUMMARY_CONTENT,
                            response_count: 17,
                            generated_at: '2026-01-02T00:00:00Z',
                            cached: false,
                            trace_id: 'trace-1',
                        },
                    ]
                },
            },
        })
        logic = surveyLogic({ id: 'test-survey' })
        logic.mount()
    })

    function renderSummary(dataProcessingAccepted: boolean): HTMLElement {
        const maxGlobalLogicInstance = maxGlobalLogic()
        maxGlobalLogicInstance.mount()
        jest.spyOn(maxGlobalLogicInstance.selectors, 'dataProcessingAccepted').mockReturnValue(dataProcessingAccepted)

        const { container } = render(
            <BindLogic logic={surveyLogic} props={{ id: 'test-survey' }}>
                <OpenQuestionSummaryV2 questionId="q1" questionIndex={0} totalResponses={17} />
            </BindLogic>
        )
        return container
    }

    it('shows the summary when the organization approved AI data processing', async () => {
        renderSummary(true)

        expect(await screen.findByText(SUMMARY_CONTENT)).toBeTruthy()
        expect(summarizeRequests).toBe(1)
    })

    it('shows nothing and requests no summary when the organization did not approve AI data processing', async () => {
        const container = renderSummary(false)

        // The component renders nothing, so there is no element to wait for. The flush gives the
        // auto-load effect the chance to start a request that it must not start.
        await act(async () => undefined)

        expect(container.firstChild).toBeNull()
        expect(screen.queryByText('Response summary')).toBeNull()
        expect(summarizeRequests).toBe(0)
    })
})
