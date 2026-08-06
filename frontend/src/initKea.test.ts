import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

function makeFailingLogic(error: ApiError): any {
    return kea<any>([
        path(['test', 'initKea', 'failingLoader']),
        loaders(() => ({
            thing: [
                null,
                {
                    loadThing: async () => {
                        throw error
                    },
                },
            ],
        })),
    ])
}

describe('initKea', () => {
    let captureException: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        silenceKeaLoadersErrors()
        captureException = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        captureException.mockRestore()
    })

    it.each([
        ['two_factor_setup_required', false],
        ['permission_denied', false],
        // Read-only mode relies on the central `before_send` filter, so it must still be captured here.
        ['read_only_blocked', true],
    ])('a 403 with code %s reports to error tracking: %s', async (code, shouldCapture) => {
        const logic = makeFailingLogic(new ApiError('nope', 403, undefined, { code }))
        logic.mount()

        await expectLogic(logic, () => logic.actions.loadThing()).toFinishAllListeners()

        expect(captureException).toHaveBeenCalledTimes(shouldCapture ? 1 : 0)
    })

    it('reports a server error to error tracking', async () => {
        const logic = makeFailingLogic(new ApiError('boom', 500))
        logic.mount()

        await expectLogic(logic, () => logic.actions.loadThing()).toFinishAllListeners()

        expect(captureException).toHaveBeenCalledTimes(1)
    })
})
