import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

function makeFailingLogic(error: unknown): ReturnType<typeof kea> {
    return kea([
        path(['test', 'initKeaFailingLoader']),
        loaders({
            thing: [
                null as null,
                {
                    loadThing: async () => {
                        throw error
                    },
                },
            ],
        }),
    ])
}

describe('initKea loader failure handling', () => {
    let errorToast: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        errorToast = jest.spyOn(lemonToast, 'error').mockImplementation((() => '') as any)
        // The handler console.errors every failure it processes; keep that expected noise out of the log.
        silenceKeaLoadersErrors()
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
    })

    it.each([
        { description: 'suppresses a scope-resolution 404', detail: 'Organization not found.', toastExpected: false },
        {
            description: 'suppresses the belong-to-an-organization 404',
            detail: 'You need to belong to an organization.',
            toastExpected: false,
        },
        {
            description: 'still toasts an ordinary 404 for a resource inside a valid scope',
            detail: 'Not found.',
            toastExpected: true,
        },
    ])('$description', async ({ detail, toastExpected }) => {
        const logic = makeFailingLogic(new ApiError('nope', 404, undefined, { detail }))
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadThing()
        }).toDispatchActions(['loadThingFailure'])

        expect(errorToast).toHaveBeenCalledTimes(toastExpected ? 1 : 0)
        logic.unmount()
    })
})
