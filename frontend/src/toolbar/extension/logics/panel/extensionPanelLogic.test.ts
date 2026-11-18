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

describe('extensionPanelLogic', () => {
    let logic: ReturnType<typeof extensionPanelLogic.build>
    let capture: jest.SpyInstance
    let currentTeamId: number
    let switchResponse: () => Response

    beforeEach(async () => {
        initKeaTests()
        currentTeamId = 1
        // The app answers the project switch with its HTML page and moves the session's project.
        switchResponse = () => HttpResponse.html('<!doctype html><title>PostHog</title>')
        useMocks({
            get: {
                [`${UI_HOST}/project/:teamId`]: ({ params }) => {
                    const response = switchResponse()
                    if (response.ok) {
                        currentTeamId = Number(params.teamId)
                    }
                    return response
                },
                [`${UI_HOST}/api/users/@me/`]: () => ({
                    distinct_id: 'user-distinct-id',
                    organization: { id: 'organization-id' },
                    team: { id: currentTeamId, project_id: currentTeamId },
                }),
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

    it('reports a successful switch when the app answers with its HTML page', async () => {
        await expectLogic(logic, () => {
            logic.actions.switchProject(2)
        })
            .toDispatchActions(['switchProject', 'loadSessionUserSuccess', 'loadToolbarAccessSuccess'])
            .toNotHaveDispatchedActions(['setProjectSwitchFailed'])
            .toMatchValues({ projectSwitchFailed: false, settingsNeeded: false })

        expect(logic.values.user?.team.id).toBe(2)
        expect(capture).toHaveBeenCalledWith('toolbar extension project switched')
    })

    it.each([
        ['the session expired', () => new HttpResponse(null, { status: 401 })],
        ['the user has no access to the project', () => new HttpResponse(null, { status: 403 })],
        ['the server fails', () => new HttpResponse(null, { status: 500 })],
        ['the network fails', () => HttpResponse.error()],
    ])('reports a failed switch when %s', async (_, response) => {
        switchResponse = response

        await expectLogic(logic, () => {
            logic.actions.switchProject(2)
        })
            .toDispatchActions(['switchProject', 'setProjectSwitchFailed', 'loadSessionUserSuccess'])
            .toMatchValues({ projectSwitchFailed: true, settingsNeeded: true })

        expect(logic.values.user?.team.id).toBe(1)
        expect(capture).not.toHaveBeenCalledWith('toolbar extension project switched')
    })

    it('clears the error when the user switches again and the switch succeeds', async () => {
        switchResponse = () => new HttpResponse(null, { status: 500 })
        await expectLogic(logic, () => {
            logic.actions.switchProject(2)
        }).toDispatchActions(['setProjectSwitchFailed', 'loadSessionUserSuccess'])
        expect(logic.values.projectSwitchFailed).toBe(true)

        switchResponse = () => HttpResponse.html('<!doctype html><title>PostHog</title>')
        await expectLogic(logic, () => {
            logic.actions.switchProject(2)
        })
            .toDispatchActions(['switchProject', 'loadSessionUserSuccess'])
            .toMatchValues({ projectSwitchFailed: false })

        expect(logic.values.user?.team.id).toBe(2)
    })
})
