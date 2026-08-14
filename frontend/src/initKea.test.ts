import { BuiltLogic, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { expectLogic } from 'kea-test-utils'

import { NetworkError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { initKeaTests } from '~/test/init'

// Mounts a loader whose action fails with `error`, so the real `onFailure` handler wired by
// `initKea` runs and we can assert what the user sees.
function mountFailingLoader(actionName: string, error: unknown): BuiltLogic {
    const logic = kea<any>([
        path(['test', 'initKea', actionName]),
        loaders({
            thing: {
                [actionName]: async () => {
                    throw error
                },
            },
        }),
    ])
    logic.mount()
    return logic
}

describe('initKea onFailure', () => {
    let toastError: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        toastError = jest.spyOn(lemonToast, 'error').mockImplementation(() => '')
    })

    afterEach(() => {
        toastError.mockRestore()
    })

    it('toasts when a write action fails with a NetworkError (no HTTP status)', async () => {
        const logic = mountFailingLoader('saveThing', new NetworkError('network'))

        await expectLogic(logic, () => logic.actions.saveThing()).toDispatchActions(['saveThingFailure'])

        expect(toastError).toHaveBeenCalledWith(
            'Save thing failed: Could not reach the server, so your change was not saved. Check your connection and try again.'
        )
    })

    it('stays silent when a load action fails with a NetworkError', async () => {
        const logic = mountFailingLoader('loadThing', new NetworkError('network'))

        await expectLogic(logic, () => logic.actions.loadThing()).toDispatchActions(['loadThingFailure'])

        expect(toastError).not.toHaveBeenCalled()
    })

    it('stays silent for a write action opted out via ERROR_FILTER_ALLOW_LIST', async () => {
        const logic = mountFailingLoader('saveEarlyAccessFeature', new NetworkError('network'))

        await expectLogic(logic, () => logic.actions.saveEarlyAccessFeature()).toDispatchActions([
            'saveEarlyAccessFeatureFailure',
        ])

        expect(toastError).not.toHaveBeenCalled()
    })
})
