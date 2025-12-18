import '@testing-library/jest-dom'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { getByDataAttr } from '~/test/byDataAttr'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, Survey, SurveySchedule, SurveyType } from '~/types'

import { SurveyView } from './SurveyView'

// Keep this test focused: avoid mounting SceneLayout/sceneLogic/router machinery.
jest.mock('~/layout/scenes/SceneLayout', () => ({
    ScenePanel: ({ children }: any) => <div>{children}</div>,
    ScenePanelActionsSection: ({ children }: any) => <div>{children}</div>,
    ScenePanelDivider: () => null,
    ScenePanelInfoSection: ({ children }: any) => <div>{children}</div>,
}))

jest.mock('~/layout/scenes/components/SceneTitleSection', () => ({
    SceneTitleSection: ({ name, actions }: any) => (
        <div>
            <div>{name}</div>
            <div>{actions}</div>
        </div>
    ),
}))

jest.mock('lib/components/AccessControlAction', () => ({
    AccessControlAction: ({ children }: any) => <>{children}</>,
}))

jest.mock('lib/components/Scenes/SceneFile', () => ({
    SceneFile: () => null,
}))

jest.mock('lib/components/Scenes/SceneDuplicate', () => ({
    SceneDuplicate: ({ onClick }: any) => <button onClick={onClick}>Duplicate</button>,
}))

jest.mock('scenes/organizationLogic', () => {
    const { kea } = require('kea')
    const organizationLogic = kea({
        reducers: {
            currentOrganization: [
                {
                    id: 'ABCD',
                    teams: [{ id: 997 }],
                    membership_level: 15,
                },
                {},
            ],
        },
    })
    return { organizationLogic }
})

jest.mock('scenes/surveys/surveysLogic', () => {
    const { kea } = require('kea')
    const surveysLogic = kea({
        actions: {
            deleteSurvey: (id: string) => ({ id }),
        },
    })
    return { surveysLogic }
})

jest.mock('scenes/surveys/surveyLogic', () => {
    const { kea } = require('kea')
    const { loaders } = require('kea-loaders')

    const testMocks = {
        updateSurveySpy: jest.fn(),
        stopSurveySpy: jest.fn(),
    }

    const surveyLogic = kea([
        {
            actions: {
                setSurvey: (survey: any) => ({ survey }),
                editingSurvey: (editing: boolean) => ({ editing }),
                setIsDuplicateToProjectModalOpen: (isOpen: boolean) => ({ isOpen }),
                duplicateSurvey: true,
            },
            reducers: {
                surveyLoading: [false, {}],
                survey: [
                    {
                        id: 'new',
                        name: '',
                        start_date: null,
                        end_date: null,
                        questions: [],
                    },
                    {
                        setSurvey: (_: any, { survey }: any) => survey,
                    },
                ],
            },
        },
        loaders(({ values }: any) => ({
            survey: {
                updateSurvey: async (payload: any) => {
                    testMocks.updateSurveySpy(payload)
                    return { ...values.survey, ...payload }
                },
                stopSurvey: async () => {
                    testMocks.stopSurveySpy()
                    return { ...values.survey, end_date: new Date().toISOString() }
                },
            },
        })),
    ])

    return { surveyLogic, __testMocks: testMocks }
})

import { surveyLogic } from 'scenes/surveys/surveyLogic'

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

        // Minimal Kea setup (we mock the logics SurveyView depends on).
        initKeaTests(false)
    })

    afterEach(() => {
        ;(surveyLogic as any).unmount?.()
        cleanup()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('does not clear end_date when scheduling a resume in the future', async () => {
        const surveyId = 'survey-1'
        const { __testMocks }: any = require('scenes/surveys/surveyLogic')
        __testMocks.updateSurveySpy.mockClear()

        ;(surveyLogic as any).mount()
        ;(surveyLogic as any).actions.setSurvey(createEndedSurvey(surveyId))

        render(<SurveyView id={surveyId} />)

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
            expect(__testMocks.updateSurveySpy).toHaveBeenCalledTimes(1)
        })

        const payload = __testMocks.updateSurveySpy.mock.calls[0][0]
        expect(payload.end_date).toBeUndefined()
        expect(payload.scheduled_start_datetime).toMatch(/^2023-01-15T/) // time depends on picker defaults
    })

    it('sets scheduled_end_datetime when scheduling a stop in the future', async () => {
        const surveyId = 'survey-2'
        const { __testMocks }: any = require('scenes/surveys/surveyLogic')
        __testMocks.updateSurveySpy.mockClear()

        ;(surveyLogic as any).mount()
        ;(surveyLogic as any).actions.setSurvey(createRunningSurvey(surveyId))

        render(<SurveyView id={surveyId} />)

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
            expect(__testMocks.updateSurveySpy).toHaveBeenCalledTimes(1)
        })

        const payload = __testMocks.updateSurveySpy.mock.calls[0][0]
        expect(payload.scheduled_end_datetime).toMatch(/^2023-01-15T/)
        expect(payload.end_date).toBeUndefined()
    })
})
