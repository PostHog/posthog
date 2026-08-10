import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { isTransientNetworkError, reverseProxyCheckerLogic } from './reverseProxyCheckerLogic'

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

    it('should not report a transient 5xx to error tracking', async () => {
        // The check is advisory, so a proxy/gateway 5xx has no user impact. Reporting it only
        // opened a fresh error tracking issue on every deploy — this locks in that it stays silent.
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => [503, { detail: 'A server error occurred' }],
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
        expect(captureExceptionSpy).not.toHaveBeenCalled()

        toastErrorSpy.mockRestore()
        captureExceptionSpy.mockRestore()
    })

    it('should report a genuinely unexpected error to error tracking', async () => {
        // A 4xx is not benign network noise, so it must still reach error tracking. Captured
        // directly (not wrapped) so the error type stays at the top of `$exception_list`, which
        // lets the central `before_send` filter recognise `ReadOnlyModeError`.
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => [400, { detail: 'Bad query' }],
            },
        })

        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadHasReverseProxy()
        }).toFinishAllListeners()

        expect(captureExceptionSpy).toHaveBeenCalledWith(
            expect.objectContaining({ status: 400 }),
            expect.objectContaining({ posthog_source: 'reverseProxyCheckerLogic.loadHasReverseProxy' })
        )

        captureExceptionSpy.mockRestore()
    })

    describe('isTransientNetworkError', () => {
        it.each([
            ['Chrome fetch rejection', new TypeError('Failed to fetch'), true],
            ['Safari fetch rejection', new TypeError('Load failed'), true],
            ['Firefox fetch rejection', new TypeError('NetworkError when attempting to fetch resource'), true],
            // The api layer wraps a dropped fetch in a statusless ApiError whose message coerces
            // from the underlying TypeError — this is the dominant production path.
            ['wrapped statusless fetch rejection', new ApiError('TypeError: Failed to fetch'), true],
            ['502 gateway error', new ApiError('Non-OK response', 502), true],
            ['503 gateway error', new ApiError('Non-OK response', 503), true],
            ['504 gateway error', new ApiError('Non-OK response', 504), true],
            ['500 backend exception', new ApiError('Non-OK response', 500), false],
            ['statusless ApiError', new ApiError('Failed to read response body'), false],
            ['4xx client error', new ApiError('Bad request', 400), false],
            ['unexpected app error', new TypeError("Cannot read properties of undefined (reading 'x')"), false],
        ])('classifies %s', (_label, error, expected) => {
            expect(isTransientNetworkError(error)).toBe(expected)
        })
    })
})
