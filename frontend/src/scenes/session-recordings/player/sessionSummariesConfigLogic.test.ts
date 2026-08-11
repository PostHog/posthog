import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { CONFIG_SAVE_TIMEOUT_MS, sessionSummariesConfigLogic } from './sessionSummariesConfigLogic'

describe('sessionSummariesConfigLogic', () => {
    let logic: ReturnType<typeof sessionSummariesConfigLogic.build>

    beforeEach(() => {
        jest.spyOn(api.sessionSummaries.config, 'get').mockResolvedValue({ product_context: '', custom_tags: {} })
        initKeaTests()
        logic = sessionSummariesConfigLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it('clears isUpdating and toasts when a save never settles', async () => {
        // A PATCH that never settles stands in for a request that hangs forever.
        jest.spyOn(api.sessionSummaries.config, 'update').mockImplementation(() => new Promise(() => {}))
        const errorToast = jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)
        jest.useFakeTimers()

        logic.actions.submitConfigForm()
        await expectLogic(logic).toMatchValues({ isUpdating: true })

        jest.advanceTimersByTime(CONFIG_SAVE_TIMEOUT_MS)

        await expectLogic(logic).toDispatchActions(['updateConfigFailure']).toMatchValues({ isUpdating: false })
        expect(errorToast).toHaveBeenCalled()
    })
})
