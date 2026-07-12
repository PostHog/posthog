import { expectLogic } from 'kea-test-utils'
import { HttpResponse } from 'msw'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

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
        // The error is captured directly (not wrapped) so its type is preserved at the
        // top of `$exception_list` — that lets the central `before_send` filter recognise
        // `ReadOnlyModeError` without depending on cause-chain serialization.
        expect(captureExceptionSpy).toHaveBeenCalledWith(
            expect.objectContaining({ status: 500 }),
            expect.objectContaining({ posthog_source: 'reverseProxyCheckerLogic.loadHasReverseProxy' })
        )

        toastErrorSpy.mockRestore()
        captureExceptionSpy.mockRestore()
    })

    it('should not capture transient network failures', async () => {
        // The advisory check fires on every scene mount, so an offline user / ad blocker /
        // cancelled request would otherwise spam error tracking with non-actionable
        // `TypeError: Failed to fetch` exceptions. These are dropped before capture.
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => HttpResponse.error(),
            },
        })

        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadHasReverseProxy()
        })
            .toFinishAllListeners()
            .toMatchValues({
                hasReverseProxy: null,
            })

        expect(captureExceptionSpy).not.toHaveBeenCalled()

        captureExceptionSpy.mockRestore()
    })

    describe('isTransientNetworkError', () => {
        it.each([
            ['TypeError: Failed to fetch (Chrome)', new TypeError('Failed to fetch'), true],
            ['Safari native Load failed', new TypeError('Load failed'), true],
            ['Firefox NetworkError', new TypeError('NetworkError when attempting to fetch resource.'), true],
            ['React Native network failure', new TypeError('Network request failed'), true],
            ['aborted request', Object.assign(new Error('aborted'), { name: 'AbortError' }), true],
            ['genuine server error', Object.assign(new Error('A server error occurred'), { status: 500 }), false],
            ['null', null, false],
            ['string', 'Failed to fetch', false],
        ])('classifies %s', (_label, error, expected) => {
            expect(isTransientNetworkError(error)).toBe(expected)
        })
    })
})
