import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SurveyType } from '~/types'

import { surveysOptInLogic } from './surveysOptInLogic'

const runningPopoverSurvey = (id: string, conditions: Record<string, unknown> | null): Record<string, unknown> => ({
    id,
    name: `Survey ${id}`,
    type: SurveyType.Popover,
    questions: [],
    conditions,
    linked_flag: null,
    linked_flag_id: null,
    targeting_flag: null,
    start_date: '2026-01-01T00:00:00Z',
    end_date: null,
    archived: false,
})

describe('surveysOptInLogic', () => {
    let logic: ReturnType<typeof surveysOptInLogic.build>
    let openDialogSpy: jest.SpyInstance
    let surveys: Record<string, unknown>[]

    beforeEach(() => {
        surveys = []
        useMocks({
            get: {
                '/api/projects/:team/surveys/': () => [200, { results: surveys, count: surveys.length }],
            },
        })
        initKeaTests()
        openDialogSpy = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
        logic = surveysOptInLogic()
        logic.mount()
    })

    afterEach(() => {
        openDialogSpy.mockRestore()
    })

    it('turns surveys on without a dialog when every running popover survey has display conditions', async () => {
        surveys = [runningPopoverSurvey('targeted', { url: 'example.com/pricing' })]

        await expectLogic(logic, () => {
            logic.actions.setSurveysOptIn(true)
        })
            .toFinishAllListeners()
            .toDispatchActions(teamLogic, ['updateCurrentTeam'])

        expect(openDialogSpy).not.toHaveBeenCalled()
    })

    it('asks for confirmation before it shows untargeted running surveys to all users', async () => {
        surveys = [
            runningPopoverSurvey('targeted', { url: 'example.com/pricing' }),
            runningPopoverSurvey('untargeted', null),
        ]

        await expectLogic(logic, () => {
            logic.actions.setSurveysOptIn(true)
        })
            .toFinishAllListeners()
            .toNotHaveDispatchedActions([teamLogic.actionTypes.updateCurrentTeam])

        expect(openDialogSpy).toHaveBeenCalledTimes(1)
        const { content, primaryButton } = openDialogSpy.mock.calls[0][0]
        expect(content.props.untargetedSurveys.map((survey: { id: string }) => survey.id)).toEqual(['untargeted'])

        await expectLogic(logic, () => {
            primaryButton.onClick()
        }).toDispatchActions(teamLogic, [teamLogic.actionCreators.updateCurrentTeam({ surveys_opt_in: true })])
    })
})
