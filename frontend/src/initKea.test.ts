import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from './initKea'

let pathCounter = 0

// Only a rejecting loader reaches the loaders plugin's onFailure, which decides what a failure
// reports. Each build needs its own path, because kea keys a logic on it.
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

    it('reports a server error with the action and the query that failed', async () => {
        const error = new ApiError('A server error occurred.', 500)
        error.queryKind = 'ErrorTrackingBreakdownsQuery'

        await failLoaderWith(error)

        expect(posthog.captureException).toHaveBeenCalledWith(error, {
            kea_action: 'loadThing',
            kea_reducer: 'thing',
            api_status: 500,
            api_query_kind: 'ErrorTrackingBreakdownsQuery',
        })
    })

    it('reports a failure that carries no query kind', async () => {
        const error = new TypeError('x is not a function')

        await failLoaderWith(error)

        expect(posthog.captureException).toHaveBeenCalledWith(
            error,
            expect.objectContaining({ kea_action: 'loadThing', api_status: null, api_query_kind: null })
        )
    })
})
