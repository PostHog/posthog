import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { reverseProxyCheckerLogic } from './reverseProxyCheckerLogic'

const useMockedResults = (proxiedRows: string[][], pageviewRows: number[][]): void => {
    useMocks({
        post: {
            '/api/environments/:team_id/query/:kind': async ({ request }) => {
                const body = JSON.stringify(await request.json())
                return [200, { results: body.includes('lib_custom_api_host') ? proxiedRows : pageviewRows }]
            },
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

    it.each([
        ['proxied pageviews', [['https://proxy.example.com']], [[1]], true],
        ['pageviews without a proxy', [], [[1]], false],
        ['no pageviews, as in an app that only sends $screen', [], [], null],
    ])('reports %s', async (_name, proxiedRows, pageviewRows, expected) => {
        useMockedResults(proxiedRows, pageviewRows)

        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadHasReverseProxy()
        })
            .toFinishAllListeners()
            .toMatchValues({
                hasReverseProxy: expected,
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
        expect(captureExceptionSpy).toHaveBeenCalledWith(
            expect.objectContaining({ status: 500 }),
            expect.objectContaining({ posthog_source: 'reverseProxyCheckerLogic.loadHasReverseProxy' })
        )

        toastErrorSpy.mockRestore()
        captureExceptionSpy.mockRestore()
    })
})
