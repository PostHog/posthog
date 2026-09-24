import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

let nextFailure: unknown

const probeLogic = kea([
    path(['test', 'initKeaFailureProbe']),
    loaders({
        thing: [
            null as string | null,
            {
                loadThing: async (): Promise<string | null> => {
                    throw nextFailure
                },
            },
        ],
    }),
])

describe('initKea loader failures', () => {
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

    // A denial can reach the browser with no DRF body to read, which is what a whole scene of
    // denied loaders looked like: one error tracking issue per loader. A 500 stays reported,
    // because that one is ours.
    it.each([
        ['a denied read with no error code', { status: 403 }, false],
        ['a denied read carrying the DRF code', { status: 403, code: 'permission_denied' }, false],
        ['a server error', { status: 500 }, true],
    ])('%s is reported to error tracking: %j -> %s', async (_name, failure, reported) => {
        nextFailure = failure
        const logic = probeLogic()
        logic.mount()
        await expectLogic(logic, () => logic.actions.loadThing()).toDispatchActions(['loadThingFailure'])
        expect(captureException).toHaveBeenCalledTimes(reported ? 1 : 0)
        logic.unmount()
    })
})
