import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

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
                // On error with no prior successful load the status stays unknown (null) rather
                // than a confirmed false — consumers gate on `=== false`, so this fails safe.
                hasReverseProxy: null,
            })

        expect(toastErrorSpy).not.toHaveBeenCalled()
        toastErrorSpy.mockRestore()
        captureExceptionSpy.mockRestore()
    })

    it.each([
        ['a 5xx server error', new ApiError('A server error occurred', 500)],
        ['a 504 timeout', new ApiError('Non-OK response (status 504: )', 504)],
        ['a wrapped network failure with no status', new ApiError(String(new TypeError('Failed to fetch')))],
        ['a raw fetch TypeError', new TypeError('Failed to fetch')],
        ['a bootstrap guard error', new Error('Team ID is not known.')],
    ])('does not capture %s to error tracking', async (_desc, error) => {
        // These failures are transient and outside a frontend fix. Capturing them only splinters
        // error tracking into one issue per environment id and status code — the reported noise.
        const queryHogQLSpy = jest.spyOn(api, 'queryHogQL').mockRejectedValue(error)
        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadHasReverseProxy()
        })
            .toFinishAllListeners()
            .toMatchValues({ hasReverseProxy: null })

        expect(captureExceptionSpy).not.toHaveBeenCalled()

        queryHogQLSpy.mockRestore()
        captureExceptionSpy.mockRestore()
    })

    it('still captures genuinely unexpected errors', async () => {
        // Guard against going blind: a 4xx from the query endpoint points to a real frontend bug
        // (e.g. a malformed query), so it must still reach error tracking.
        const queryHogQLSpy = jest.spyOn(api, 'queryHogQL').mockRejectedValue(new ApiError('Bad request', 400))
        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadHasReverseProxy()
        }).toFinishAllListeners()

        expect(captureExceptionSpy).toHaveBeenCalledWith(
            expect.objectContaining({ status: 400 }),
            expect.objectContaining({ posthog_source: 'reverseProxyCheckerLogic.loadHasReverseProxy' })
        )

        queryHogQLSpy.mockRestore()
        captureExceptionSpy.mockRestore()
    })

    it('throttle survives a remount so a page reload does not re-fire the query', async () => {
        // Regression test: the throttle used to live in per-mount `cache`, so every reload re-ran
        // the advisory query and burned ClickHouse compute. It now persists in localStorage.
        const queryHogQLSpy = jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as any)

        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.loadHasReverseProxy()
        }).toFinishAllListeners()

        // Unmounting clears the logic's `cache`; a fresh mount simulates a page reload.
        logic.unmount()
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.loadHasReverseProxy()
        }).toFinishAllListeners()

        expect(queryHogQLSpy).toHaveBeenCalledTimes(1)

        queryHogQLSpy.mockRestore()
    })
})
