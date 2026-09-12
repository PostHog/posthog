import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from './initKea'

let pathCounter = 0

// Only a rejecting loader reaches the loaders plugin's onFailure, which is what decides whether a
// failure is toasted, logged and reported. Each build needs its own path, since kea keys on it.
async function failLoaderWith(error: unknown): Promise<void> {
    pathCounter += 1
    const logic = kea<any>([
        path(['test', 'initKea', `failure${pathCounter}`]),
        loaders(() => ({
            thing: [
                null as string | null,
                {
                    loadThing: async () => {
                        throw error
                    },
                },
            ],
        })),
    ])
    logic.mount()
    logic.actions.loadThing()
    await expectLogic(logic).toFinishAllListeners()
    logic.unmount()
}

describe('initKea', () => {
    beforeEach(() => {
        initKeaTests()
        silenceKeaLoadersErrors()
        jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
    })

    it('reports a server error with the action that failed', async () => {
        const error = new ApiError('A server error occurred.', 500)

        await failLoaderWith(error)

        expect(posthog.captureException).toHaveBeenCalledWith(
            error,
            expect.objectContaining({ kea_action: 'loadThing', kea_reducer: 'thing', api_status: 500 })
        )
    })
})
