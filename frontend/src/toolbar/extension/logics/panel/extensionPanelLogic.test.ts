import { expectLogic } from 'kea-test-utils'
import { HttpResponse } from 'msw'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { toolbarPosthogJS } from '~/toolbar/shared/toolbarPosthogJS'

import { extensionPanelLogic } from './extensionPanelLogic'

jest.mock('../../browser/extensionBrowser', () => ({
    getActiveTab: jest.fn(async () => ({ id: 1, url: 'https://example.com/' })),
    getStoredUiHost: jest.fn(async () => 'https://us.posthog.com'),
    hasHostPermission: jest.fn(async () => true),
    onActiveTabChange: jest.fn(() => () => undefined),
    openTab: jest.fn(async () => undefined),
    requestHostPermission: jest.fn(async () => true),
    setStoredUiHost: jest.fn(async () => undefined),
}))

const UI_HOST = 'https://us.posthog.com'
const APP_PAGE = '<!doctype html><title>PostHog</title>'

// What the app does with `GET /project/<id>`. It answers a switch it allows and a switch it refuses alike, with its
// HTML page and a 200, and an expired session follows a redirect to the login page, which also answers with a 200.
type SwitchOutcome = 'switches' | 'refuses' | 'signs out' | 'fails' | 'network error'

describe('extensionPanelLogic', () => {
    let logic: ReturnType<typeof extensionPanelLogic.build>
    let capture: jest.SpyInstance
    let currentTeamId: number
    let signedIn: boolean
    let switchOutcome: SwitchOutcome

    beforeEach(async () => {
        initKeaTests()
        currentTeamId = 1
        signedIn = true
        switchOutcome = 'switches'
        useMocks({
            get: {
                [`${UI_HOST}/project/:teamId`]: ({ params }) => {
                    switch (switchOutcome) {
                        case 'switches':
                            currentTeamId = Number(params.teamId)
                            return HttpResponse.html(APP_PAGE)
                        case 'refuses':
                            return HttpResponse.html(APP_PAGE)
                        case 'signs out':
                            signedIn = false
                            return HttpResponse.html(APP_PAGE)
                        case 'fails':
                            return new HttpResponse(null, { status: 500 })
                        case 'network error':
                            return HttpResponse.error()
                    }
                },
                [`${UI_HOST}/api/users/@me/`]: () =>
                    signedIn
                        ? {
                              distinct_id: 'user-distinct-id',
                              organization: { id: 'organization-id' },
                              team: { id: currentTeamId, project_id: currentTeamId },
                          }
                        : [401, { detail: 'Authentication credentials were not provided.' }],
                [`${UI_HOST}/api/user/toolbar_entitlements`]: { entitlements: {} },
            },
        })
        capture = jest.spyOn(toolbarPosthogJS, 'capture').mockImplementation(() => undefined)
        jest.spyOn(toolbarPosthogJS, 'identify').mockImplementation(() => undefined)

        logic = extensionPanelLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSessionUserSuccess', 'loadToolbarAccessSuccess'])
        expect(logic.values.user?.team.id).toBe(1)
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('reports a successful switch when the session moves to the project', async () => {
        await expectLogic(logic, () => {
            logic.actions.switchProject(2)
        })
            .toDispatchActions(['switchProject', 'loadSessionUserSuccess', 'loadToolbarAccessSuccess'])
            .toNotHaveDispatchedActions(['setProjectSwitchFailed'])
            .toMatchValues({ projectSwitchFailed: false, settingsNeeded: false })

        expect(logic.values.user?.team.id).toBe(2)
        expect(capture).toHaveBeenCalledWith('toolbar extension project switched')
    })

    it.each<[string, SwitchOutcome]>([
        ['the app refuses the switch', 'refuses'],
        ['the session expired', 'signs out'],
        ['the server fails', 'fails'],
        ['the network fails', 'network error'],
    ])('reports a failed switch when %s', async (_, outcome) => {
        switchOutcome = outcome

        await expectLogic(logic, () => {
            logic.actions.switchProject(2)
        })
            .toDispatchActions(['switchProject', 'setProjectSwitchFailed', 'loadSessionUserSuccess'])
            .toMatchValues({ projectSwitchFailed: true, settingsNeeded: true })

        expect(logic.values.user?.team.id).not.toBe(2)
        expect(capture).not.toHaveBeenCalledWith('toolbar extension project switched')
    })

    it('clears the error when the user switches again and the switch succeeds', async () => {
        switchOutcome = 'refuses'
        await expectLogic(logic, () => {
            logic.actions.switchProject(2)
        }).toDispatchActions(['setProjectSwitchFailed', 'loadSessionUserSuccess'])
        expect(logic.values.projectSwitchFailed).toBe(true)

        switchOutcome = 'switches'
        await expectLogic(logic, () => {
            logic.actions.switchProject(2)
        })
            .toDispatchActions(['switchProject', 'loadSessionUserSuccess'])
            .toMatchValues({ projectSwitchFailed: false })

        expect(logic.values.user?.team.id).toBe(2)
    })
})
