import { initKeaTests } from '~/test/init'
import { toolbarApi } from '~/toolbar/toolbarApi'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

// Keep the real toolbar posthog-js instance but spy on the exception capture helper so we
// can assert what does and doesn't reach error tracking.
jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    ...jest.requireActual('~/toolbar/toolbarPosthogJS'),
    captureToolbarException: jest.fn(),
}))

describe('toolbarApi', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        jest.spyOn(console, 'warn').mockImplementation()
        jest.spyOn(console, 'error').mockImplementation()
        initKeaTests()
        // A mounted config with an access token lets toolbarFetch actually hit `global.fetch`
        // instead of short-circuiting to a stub 401.
        toolbarConfigLogic.build({ apiURL: 'http://localhost', accessToken: 'test-token' }).mount()
    })

    it('does not report network-level fetch rejections to error tracking, but does telemeter them', async () => {
        const { captureToolbarException, toolbarPosthogJS } = jest.requireMock('~/toolbar/toolbarPosthogJS')
        const captureSpy = jest.spyOn(toolbarPosthogJS, 'capture').mockImplementation()
        global.fetch = jest.fn(() => Promise.reject(new TypeError('Failed to fetch')))

        const result = await toolbarApi.webExperiments.list({ context: 'load_experiments' })

        if (result.ok) {
            throw new Error('expected the network failure to produce a failure result')
        }
        expect(result.error.isNetworkError).toBe(true)
        expect(captureToolbarException).not.toHaveBeenCalled()
        expect(captureSpy).toHaveBeenCalledWith(
            'toolbar api request',
            expect.objectContaining({ context: 'load_experiments', status: 0, network_error: true })
        )
    })

    it('still reports 5xx responses to error tracking', async () => {
        const { captureToolbarException } = jest.requireMock('~/toolbar/toolbarPosthogJS')
        global.fetch = jest.fn(() =>
            Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) } as Response)
        )

        const result = await toolbarApi.webExperiments.list({ context: 'load_experiments' })

        expect(result.ok).toBe(false)
        expect(result.status).toBe(500)
        expect(captureToolbarException).toHaveBeenCalledWith(expect.any(Error), 'load_experiments', { status: 500 })
    })
})
