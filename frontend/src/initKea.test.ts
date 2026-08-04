import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

describe('initKea onFailure', () => {
    let captureExceptionSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation()
    })

    afterEach(() => {
        captureExceptionSpy.mockRestore()
    })

    test.each([
        // The toast-suppression predicate (isAccessDeniedError) must also gate reporting, or every
        // gated loader mints a fresh error-tracking issue for expected, already-handled control flow.
        [
            'a permission-denied 403 (access-denied, already handled by the scene gate)',
            new ApiError("You don't have access to the project.", 403, undefined, { code: 'permission_denied' }),
            false,
        ],
        ['a read-only 403 (different code, not access-denied)', new ApiError('Read-only', 403, undefined, {}), true],
        ['a 500', new ApiError('Server error', 500, undefined, {}), true],
    ])('%s', async (_name, error, shouldReport) => {
        const logic = kea([
            path(['initKea', 'test', String(Math.random())]),
            loaders({
                thing: [
                    '',
                    {
                        loadThing: async () => {
                            throw error
                        },
                    },
                ],
            }),
        ])
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadThing()
        }).toDispatchActions(['loadThingFailure'])

        if (shouldReport) {
            expect(captureExceptionSpy).toHaveBeenCalledWith(error)
        } else {
            expect(captureExceptionSpy).not.toHaveBeenCalled()
        }
        logic.unmount()
    })
})
