import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ReadOnlyModeError } from 'lib/readOnlyGuard'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { reverseProxyCheckerLogic } from './reverseProxyCheckerLogic'

const hasReverseProxyValues = [['https://proxy.example.com'], [null]]
const doesNotHaveReverseProxyValues = [[null], [null]]

const useMockedValues = (results: (string | null)[][]): void => {
    useMocks({
        post: {
            '/api/environments/:team_id/query/:kind': () => [
                200,
                {
                    results,
                },
            ],
        },
    })
}

describe('reverseProxyCheckerLogic', () => {
    let logic: ReturnType<typeof reverseProxyCheckerLogic.build>

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
        logic = reverseProxyCheckerLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('should not have a reverse proxy set - when no data', async () => {
        useMockedValues([])

        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadHasReverseProxy()
        })
            .toFinishAllListeners()
            .toMatchValues({
                hasReverseProxy: false,
            })
    })

    it('should not have a reverse proxy set - when data with no lib_custom_api_host values', async () => {
        useMockedValues(doesNotHaveReverseProxyValues)

        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadHasReverseProxy()
        })
            .toFinishAllListeners()
            .toMatchValues({
                hasReverseProxy: false,
            })
    })

    it('should have a reverse proxy set', async () => {
        useMockedValues(hasReverseProxyValues)

        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadHasReverseProxy()
        })
            .toFinishAllListeners()
            .toMatchValues({
                hasReverseProxy: true,
            })
    })

    it('should swallow server errors silently instead of showing a toast', async () => {
        // Regression test: previously a 500 from the HogQL endpoint would propagate
        // through kea-loaders and surface a user-visible
        // 'Load has reverse proxy failed: A server error occurred' toast on every
        // scene that mounts ProductSetupButton.
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => [500, { detail: 'A server error occurred' }],
            },
        })

        const toastErrorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => '')
        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadHasReverseProxy()
        })
            .toFinishAllListeners()
            .toMatchValues({
                hasReverseProxy: false,
            })

        expect(toastErrorSpy).not.toHaveBeenCalled()
        expect(captureExceptionSpy).toHaveBeenCalledWith(
            expect.objectContaining({
                message: expect.stringContaining('reverseProxyCheckerLogic: loadHasReverseProxy query failed'),
            })
        )

        toastErrorSpy.mockRestore()
        captureExceptionSpy.mockRestore()
    })

    it.each([
        ['TypeError: Failed to fetch', new TypeError('Failed to fetch')],
        ['AbortError', Object.assign(new Error('The operation was aborted.'), { name: 'AbortError' })],
        [
            'NetworkError',
            Object.assign(new Error('NetworkError when attempting to fetch resource.'), { name: 'NetworkError' }),
        ],
        [
            'TypeError: Failed to fetch wrapped as cause',
            new Error('wrapper', { cause: new TypeError('Failed to fetch') }),
        ],
    ])('should not report transient network errors to error tracking - %s', async (_label, thrownError) => {
        // Regression: browser-level fetch failures (offline, ad-blockers, mid-navigation
        // aborts) are environmental noise — afterMount fires on every scene, so reporting
        // them floods error tracking with non-actionable issues.
        const queryHogQLSpy = jest.spyOn(api, 'queryHogQL').mockRejectedValue(thrownError)

        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        try {
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.loadHasReverseProxy()
            })
                .toFinishAllListeners()
                .toMatchValues({
                    hasReverseProxy: false,
                })

            expect(captureExceptionSpy).not.toHaveBeenCalled()
        } finally {
            captureExceptionSpy.mockRestore()
            queryHogQLSpy.mockRestore()
        }
    })

    it('should not report read-only mode blocks to error tracking', async () => {
        // Regression: ReadOnlyModeError from loadHasReverseProxy must be swallowed,
        // otherwise every scene mount would spam error tracking via afterMount.
        //
        // We mock api.queryHogQL directly because /query is allow-listed in
        // readOnlyGuard, so setReadOnlyGetter wouldn't fire here.
        const queryHogQLSpy = jest.spyOn(api, 'queryHogQL').mockRejectedValue(new ReadOnlyModeError())

        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        try {
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.loadHasReverseProxy()
            })
                .toFinishAllListeners()
                .toMatchValues({
                    hasReverseProxy: false,
                })

            expect(captureExceptionSpy).not.toHaveBeenCalled()
        } finally {
            captureExceptionSpy.mockRestore()
            queryHogQLSpy.mockRestore()
        }
    })
})
