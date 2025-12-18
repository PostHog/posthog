import '@testing-library/jest-dom'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { useMocks } from '~/mocks/jest'
import { getByDataAttr } from '~/test/byDataAttr'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, Survey, SurveySchedule, SurveyType } from '~/types'

import { SurveyView } from './SurveyView'
import { surveyLogic } from './surveyLogic'

jest.mock('lib/hooks/useFileSystemLogView', () => ({
    useFileSystemLogView: () => {},
}))

jest.mock('scenes/hog-functions/list/LinkedHogFunctions', () => ({
    LinkedHogFunctions: () => null,
}))

jest.mock('scenes/surveys/SurveyOverview', () => ({
    SurveyOverview: () => null,
}))

jest.mock('scenes/surveys/SurveyResponseFilters', () => ({
    SurveyResponseFilters: () => null,
}))

jest.mock('scenes/surveys/SurveyStatsSummary', () => ({
    SurveyStatsSummary: () => null,
}))

jest.mock('./SurveyHeadline', () => ({
    SurveyHeadline: () => null,
}))

jest.mock('./SurveySettings', () => ({
    SurveysDisabledBanner: () => null,
}))

jest.mock('~/queries/Query/Query', () => ({
    Query: () => null,
}))

const createBaseSurvey = ({ id, name }: { id: string; name: string }): Survey =>
    ({
        id,
        name,
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
        archived: false,
        targeting_flag_filters: undefined,
        responses_limit: null,
        iteration_count: null,
        iteration_frequency_days: null,
        schedule: SurveySchedule.Once,
        scheduled_start_datetime: null,
        scheduled_end_datetime: null,
        user_access_level: AccessControlLevel.Editor,
    }) as unknown as Survey

const createEndedSurvey = (id: string): Survey =>
    ({
        ...createBaseSurvey({ id, name: 'Ended survey' }),
        name: 'Ended survey',
        start_date: '2024-01-01T00:00:00Z',
        end_date: '2024-01-02T00:00:00Z',
    }) as unknown as Survey

const createRunningSurvey = (id: string): Survey =>
    ({
        ...createBaseSurvey({ id, name: 'Running survey' }),
        name: 'Running survey',
        start_date: '2024-01-01T00:00:00Z',
        end_date: null,
    }) as unknown as Survey

describe('SurveyView lifecycle dialogs', () => {
    beforeEach(() => {
        window.HTMLElement.prototype.scrollIntoView = jest.fn()
        jest.useFakeTimers().setSystemTime(new Date('2023-01-10T17:22:08.000Z'))

        initKeaTests()

        useMocks({
            get: {
                // organizationLogic requires `membership_level`, otherwise it treats the org as unavailable and redirects.
                '/api/organizations/@current*': () => [
                    200,
                    {
                        id: 'ABCD',
                        teams: [{ id: 997 }],
                        membership_level: 15,
                    },
                ],
                '/api/sdk_doctor*': () => [200, {}],
                '/api/user_home_settings/@me*': () => [200, { tabs: [], homepage: null }],
                '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                '/api/projects/:team_id/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                '/api/projects/:team/surveys/responses_count*': () => [200, {}],
                '/api/projects/:team_id/surveys/responses_count*': () => [200, {}],
                '/api/projects/:team/surveys/:id/archived-response-uuids/': () => [200, []],
                '/api/projects/:team/surveys/:id/archived-response-uuids': () => [200, []],
                '/api/projects/:team_id/surveys/:id/archived-response-uuids/': () => [200, []],
                '/api/projects/:team_id/surveys/:id/archived-response-uuids': () => [200, []],
            },
            post: {
                // surveyLogic uses HogQL queries for stats; return minimal shapes to avoid network errors.
                '/api/environments/:team_id/query*': async (req) => {
                    const body: any = await req.json()
                    const queryText: string = body?.query?.query || body?.query || ''
                    if (queryText.includes('QUERYING DISMISSED AND SENT COUNT')) {
                        return [200, { results: [[0]] }]
                    }
                    return [200, { results: [] }]
                },
            },
            patch: {
                '/api/environments/@current/add_product_intent/': () => [200, {}],
                '/api/environments/@current/add_product_intent': () => [200, {}],
                '/api/user_home_settings/@me*': () => [200, {}],
            },
        })
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('does not clear end_date when scheduling a resume in the future', async () => {
        const surveyId = 'survey-1'
        let capturedRequest: any
        useMocks({
            get: {
                '/api/projects/:team/surveys/:id': () => [200, createEndedSurvey(surveyId)],
                '/api/projects/:team/surveys/:id/': () => [200, createEndedSurvey(surveyId)],
                '/api/projects/:team_id/surveys/:id': () => [200, createEndedSurvey(surveyId)],
                '/api/projects/:team_id/surveys/:id/': () => [200, createEndedSurvey(surveyId)],
            },
            patch: {
                '/api/projects/:team/surveys/:id': async (req) => {
                    capturedRequest = await req.json()
                    return [
                        200,
                        {
                            ...createEndedSurvey(surveyId),
                            scheduled_start_datetime: capturedRequest.scheduled_start_datetime,
                        },
                    ]
                },
                '/api/projects/:team/surveys/:id/': async (req) => {
                    capturedRequest = await req.json()
                    return [
                        200,
                        {
                            ...createEndedSurvey(surveyId),
                            scheduled_start_datetime: capturedRequest.scheduled_start_datetime,
                        },
                    ]
                },
                '/api/projects/:team_id/surveys/:id': async (req) => {
                    capturedRequest = await req.json()
                    return [
                        200,
                        {
                            ...createEndedSurvey(surveyId),
                            scheduled_start_datetime: capturedRequest.scheduled_start_datetime,
                        },
                    ]
                },
                '/api/projects/:team_id/surveys/:id/': async (req) => {
                    capturedRequest = await req.json()
                    return [
                        200,
                        {
                            ...createEndedSurvey(surveyId),
                            scheduled_start_datetime: capturedRequest.scheduled_start_datetime,
                        },
                    ]
                },
            },
        })

        render(
            <BindLogic logic={surveyLogic} props={{ id: surveyId }}>
                <SurveyView id={surveyId} />
            </BindLogic>
        )

        await screen.findByText('Ended survey')

        await userEvent.click(screen.getByRole('button', { name: 'Resume' }))

        await userEvent.click(await screen.findByText('In the future'))

        const dateTimeButton = await screen.findByRole('button', { name: /January 10, 2023/ })
        await userEvent.click(dateTimeButton)

        const monthElement = document.body.querySelector('.LemonCalendar__month') as HTMLElement
        expect(monthElement).toBeTruthy()
        await userEvent.click(await within(monthElement).findByText('15'))
        await userEvent.click(getByDataAttr(document.body, 'lemon-calendar-select-apply'))

        await userEvent.click(screen.getByRole('button', { name: 'Schedule resume' }))

        await waitFor(() => {
            expect(capturedRequest).toBeTruthy()
        })

        await waitFor(() => {
            expect(screen.queryByText('Resume this survey?')).not.toBeInTheDocument()
        })

        expect(capturedRequest.end_date).toBeUndefined()
        expect(capturedRequest.scheduled_start_datetime).toMatch(/^2023-01-15T/) // time depends on picker defaults
    })

    it('sets scheduled_end_datetime when scheduling a stop in the future', async () => {
        const surveyId = 'survey-2'
        let capturedRequest: any
        useMocks({
            get: {
                '/api/projects/:team/surveys/:id': () => [200, createRunningSurvey(surveyId)],
                '/api/projects/:team/surveys/:id/': () => [200, createRunningSurvey(surveyId)],
                '/api/projects/:team_id/surveys/:id': () => [200, createRunningSurvey(surveyId)],
                '/api/projects/:team_id/surveys/:id/': () => [200, createRunningSurvey(surveyId)],
            },
            patch: {
                '/api/projects/:team/surveys/:id': async (req) => {
                    capturedRequest = await req.json()
                    return [
                        200,
                        {
                            ...createRunningSurvey(surveyId),
                            scheduled_end_datetime: capturedRequest.scheduled_end_datetime,
                        },
                    ]
                },
                '/api/projects/:team/surveys/:id/': async (req) => {
                    capturedRequest = await req.json()
                    return [
                        200,
                        {
                            ...createRunningSurvey(surveyId),
                            scheduled_end_datetime: capturedRequest.scheduled_end_datetime,
                        },
                    ]
                },
                '/api/projects/:team_id/surveys/:id': async (req) => {
                    capturedRequest = await req.json()
                    return [
                        200,
                        {
                            ...createRunningSurvey(surveyId),
                            scheduled_end_datetime: capturedRequest.scheduled_end_datetime,
                        },
                    ]
                },
                '/api/projects/:team_id/surveys/:id/': async (req) => {
                    capturedRequest = await req.json()
                    return [
                        200,
                        {
                            ...createRunningSurvey(surveyId),
                            scheduled_end_datetime: capturedRequest.scheduled_end_datetime,
                        },
                    ]
                },
            },
        })

        render(
            <BindLogic logic={surveyLogic} props={{ id: surveyId }}>
                <SurveyView id={surveyId} />
            </BindLogic>
        )

        await screen.findByText('Running survey')

        await userEvent.click(screen.getByRole('button', { name: 'Stop' }))

        await userEvent.click(await screen.findByText('In the future'))

        const dateTimeButton = await screen.findByRole('button', { name: /January 10, 2023/ })
        await userEvent.click(dateTimeButton)

        const monthElement = document.body.querySelector('.LemonCalendar__month') as HTMLElement
        expect(monthElement).toBeTruthy()
        await userEvent.click(await within(monthElement).findByText('15'))
        await userEvent.click(getByDataAttr(document.body, 'lemon-calendar-select-apply'))

        await userEvent.click(screen.getByRole('button', { name: 'Schedule stop' }))

        await waitFor(() => {
            expect(capturedRequest).toBeTruthy()
        })

        await waitFor(() => {
            expect(screen.queryByText('Stop this survey?')).not.toBeInTheDocument()
        })

        expect(capturedRequest.scheduled_end_datetime).toMatch(/^2023-01-15T/)
        expect(capturedRequest.end_date).toBeUndefined()
    })
})
