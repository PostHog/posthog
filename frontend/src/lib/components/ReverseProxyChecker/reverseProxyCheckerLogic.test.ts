import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { reverseProxyCheckerLogic } from './reverseProxyCheckerLogic'

const CHECK_URL = '/api/projects/:team_id/reverse_proxy/check/'

function setAppContextCheck(hasReverseProxy: boolean | undefined, teamId: number = MOCK_DEFAULT_TEAM.id): void {
    window.POSTHOG_APP_CONTEXT = {
        ...window.POSTHOG_APP_CONTEXT!,
        current_team: { ...MOCK_DEFAULT_TEAM, id: teamId },
        has_reverse_proxy: hasReverseProxy,
    }
}

describe('reverseProxyCheckerLogic', () => {
    let logic: ReturnType<typeof reverseProxyCheckerLogic.build>
    let checkRequest: jest.Mock

    function useCheckMock(hasReverseProxy: boolean): void {
        checkRequest = jest.fn(() => [200, { has_reverse_proxy: hasReverseProxy }])
        useMocks({ get: { [CHECK_URL]: checkRequest } })
    }

    beforeEach(() => {
        initKeaTests()
        setAppContextCheck(undefined)
        logic = reverseProxyCheckerLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        {
            name: 'uses a cached proxy from the app context',
            context: true,
            contextTeamOffset: 0,
            expected: true,
            requests: 0,
        },
        {
            name: 'uses a cached miss from the app context',
            context: false,
            contextTeamOffset: 0,
            expected: false,
            requests: 0,
        },
        {
            name: 'asks the server when the app context has no answer',
            context: undefined,
            contextTeamOffset: 0,
            expected: true,
            requests: 1,
        },
        {
            name: 'asks the server when the app context is for another team',
            context: false,
            contextTeamOffset: 1,
            expected: true,
            requests: 1,
        },
    ])('on mount, $name', async ({ context, contextTeamOffset, expected, requests }) => {
        useCheckMock(true)
        setAppContextCheck(context, MOCK_DEFAULT_TEAM.id + contextTeamOffset)

        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadHasReverseProxySuccess'])
            .toFinishAllListeners()
            .toMatchValues({ hasReverseProxy: expected })

        expect(checkRequest).toHaveBeenCalledTimes(requests)
    })

    it.each([true, false])('returns the server answer %s and throttles repeat checks', async (hasReverseProxy) => {
        useCheckMock(hasReverseProxy)

        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.loadHasReverseProxy()
        })
            .toFinishAllListeners()
            .toMatchValues({ hasReverseProxy })

        expect(checkRequest).toHaveBeenCalledTimes(1)
    })

    it('marks the reverse proxy setup task complete when a proxy is found', async () => {
        useCheckMock(true)
        globalSetupLogic.mount()

        logic.mount()

        await expectLogic(globalSetupLogic).toDispatchActions([
            globalSetupLogic.actionCreators.markTaskAsCompleted(SetupTaskId.SetUpReverseProxy),
        ])
        globalSetupLogic.unmount()
    })

    it('should swallow server errors silently instead of showing a toast', async () => {
        useMocks({ get: { [CHECK_URL]: () => [500, { detail: 'A server error occurred' }] } })

        const toastErrorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => '')
        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadHasReverseProxy()
        })
            .toFinishAllListeners()
            .toMatchValues({
                // On error with no prior successful load the status stays unknown (null) rather
                // than a confirmed false — consumers gate on `=== false`, so this fails safe.
                hasReverseProxy: null,
            })

        expect(toastErrorSpy).not.toHaveBeenCalled()
        expect(captureExceptionSpy).toHaveBeenCalledWith(
            expect.objectContaining({ status: 500 }),
            expect.objectContaining({ posthog_source: 'reverseProxyCheckerLogic.loadHasReverseProxy' })
        )

        toastErrorSpy.mockRestore()
        captureExceptionSpy.mockRestore()
    })
})
