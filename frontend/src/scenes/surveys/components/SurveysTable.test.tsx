import '@testing-library/jest-dom'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useMocks } from '~/mocks/jest'
import { getByDataAttr } from '~/test/byDataAttr'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, Survey, SurveySchedule, SurveyType } from '~/types'

import { SurveysTable } from './SurveysTable'

const createEndedSurvey = (): Survey => ({
    id: 'survey-1',
    name: 'Ended survey',
    description: '',
    type: SurveyType.Popover,
    linked_flag_id: null,
    linked_flag: null,
    targeting_flag: null,
    questions: [{ type: 'open', question: 'How was it?' }] as any,
    conditions: null,
    appearance: null,
    created_at: '2024-01-01T00:00:00Z',
    created_by: null,
    start_date: '2024-01-01T00:00:00Z',
    end_date: '2024-01-02T00:00:00Z',
    archived: false,
    targeting_flag_filters: undefined,
    responses_limit: null,
    iteration_count: null,
    iteration_frequency_days: null,
    schedule: SurveySchedule.Once,
    scheduled_start_datetime: null,
    scheduled_end_datetime: null,
    user_access_level: AccessControlLevel.Editor,
})

describe('SurveysTable resume scheduling', () => {
    beforeEach(() => {
        window.HTMLElement.prototype.scrollIntoView = jest.fn()
        jest.useFakeTimers().setSystemTime(new Date('2023-01-10T17:22:08.000Z'))

        initKeaTests()

        useMocks({
            get: {
                // surveysLogic uses `:team` in some tests and `:team_id` in others, so support both.
                '/api/projects/:team/surveys/': () => [
                    200,
                    {
                        count: 1,
                        results: [createEndedSurvey()],
                        next: null,
                        previous: null,
                    },
                ],
                '/api/projects/:team_id/surveys/': () => [
                    200,
                    {
                        count: 1,
                        results: [createEndedSurvey()],
                        next: null,
                        previous: null,
                    },
                ],
                '/api/projects/:team/surveys/responses_count': () => [200, {}],
                '/api/projects/:team_id/surveys/responses_count': () => [200, {}],
                '/api/projects/:team_id/surveys/responses_count/': () => [200, {}],
                '/api/sdk_doctor/': () => [200, {}],
            },
            patch: {
                '/api/environments/@current/add_product_intent/': () => [200, {}],
                '/api/environments/@current/add_product_intent': () => [200, {}],
            },
        })
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('does not clear end_date when scheduling a resume in the future', async () => {
        let capturedRequest: any
        let productIntentRequests = 0
        useMocks({
            patch: {
                '/api/projects/:team/surveys/:id': async (req) => {
                    capturedRequest = await req.json()
                    return [
                        200,
                        { ...createEndedSurvey(), scheduled_start_datetime: capturedRequest.scheduled_start_datetime },
                    ]
                },
                '/api/projects/:team/surveys/:id/': async (req) => {
                    capturedRequest = await req.json()
                    return [
                        200,
                        { ...createEndedSurvey(), scheduled_start_datetime: capturedRequest.scheduled_start_datetime },
                    ]
                },
                '/api/projects/:team_id/surveys/:id': async (req) => {
                    capturedRequest = await req.json()
                    return [
                        200,
                        { ...createEndedSurvey(), scheduled_start_datetime: capturedRequest.scheduled_start_datetime },
                    ]
                },
                '/api/projects/:team_id/surveys/:id/': async (req) => {
                    capturedRequest = await req.json()
                    return [
                        200,
                        { ...createEndedSurvey(), scheduled_start_datetime: capturedRequest.scheduled_start_datetime },
                    ]
                },
                '/api/environments/@current/add_product_intent/': () => {
                    productIntentRequests += 1
                    return [200, {}]
                },
                '/api/environments/@current/add_product_intent': () => {
                    productIntentRequests += 1
                    return [200, {}]
                },
            },
        })

        render(<SurveysTable />)

        // Wait for survey row to render
        await screen.findByText('Ended survey')

        // Open row actions
        await userEvent.click(screen.getByRole('button', { name: 'more' }))
        await userEvent.click(await screen.findByRole('button', { name: 'Resume survey' }))

        // Switch to datetime mode
        await userEvent.click(screen.getByText('In the future'))

        // Open calendar popover (initial value is now)
        await userEvent.click(await screen.findByRole('button', { name: 'January 10, 2023 17:22' }))

        // Pick a future date (15th) and apply
        const monthElement = document.body.querySelector('.LemonCalendar__month') as HTMLElement
        expect(monthElement).toBeTruthy()
        await userEvent.click(await within(monthElement).findByText('15'))
        await userEvent.click(getByDataAttr(document.body, 'lemon-calendar-select-apply'))

        // Submit
        await userEvent.click(screen.getByRole('button', { name: 'Schedule resume' }))

        await waitFor(() => {
            expect(capturedRequest).toBeTruthy()
        })

        // Ensure the async update flow completes before test cleanup
        await waitFor(() => {
            expect(screen.queryByText('Resume this survey?')).not.toBeInTheDocument()
        })

        await waitFor(() => {
            expect(productIntentRequests).toBeGreaterThanOrEqual(1)
        })

        expect(capturedRequest.end_date).toBeUndefined()
        expect(capturedRequest.scheduled_start_datetime).toMatch(/^2023-01-15T17:22:00\.000Z$/)
    })
})
