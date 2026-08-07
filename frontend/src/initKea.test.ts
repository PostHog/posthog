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
        errorToast = jest.spyOn(lemonToast, 'error').mockImplementation((() => '') as any)
        // The handler console.errors every failure it processes; keep that expected noise out of the log.
        silenceKeaLoadersErrors()
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
    })

    it('suppresses an org-less 404 scope error when there is no current organization', async () => {
        // organizationLogic is not mounted, so the handler sees no current organization
        initKeaTests(false)
        const logic = makeFailingLogic(new ApiError('nope', 404, undefined, { detail: 'Organization not found.' }))
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadThing()
        }).toDispatchActions(['loadThingFailure'])

        expect(errorToast).not.toHaveBeenCalled()
        logic.unmount()
    })

    it('still toasts a 404 scope error when the user has a current organization', async () => {
        // mountCommonLogic mounts organizationLogic with a current org from the app context
        initKeaTests()
        const logic = makeFailingLogic(new ApiError('nope', 404, undefined, { detail: 'Organization not found.' }))
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadThing()
        }).toDispatchActions(['loadThingFailure'])

        expect(errorToast).toHaveBeenCalled()
        logic.unmount()
    })
})
