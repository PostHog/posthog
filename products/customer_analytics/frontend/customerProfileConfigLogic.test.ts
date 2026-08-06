import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'
import { CustomerProfileScope } from '~/types'

import { customerProfileConfigLogic } from './customerProfileConfigLogic'

describe('customerProfileConfigLogic', () => {
    let logic: ReturnType<typeof customerProfileConfigLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('degrades a project-not-found fetch to no configs without interrupting the user', async () => {
        // loadConfigs fires on mount; an unresolvable project 404s it. It must not toast or rethrow
        // on a core scene like Persons — just show no configs.
        jest.spyOn(api.customerProfileConfigs, 'list').mockRejectedValue(new ApiError('Project not found.', 404))

        logic = customerProfileConfigLogic({ scope: CustomerProfileScope.PERSON })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadConfigsSuccess'])
            .toNotHaveDispatchedActions(['loadConfigsFailure'])
        expect(logic.values.configs).toEqual([])
        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('still surfaces a non-404 fetch failure with a toast', async () => {
        jest.spyOn(api.customerProfileConfigs, 'list').mockRejectedValue(new ApiError('boom', 500))

        logic = customerProfileConfigLogic({ scope: CustomerProfileScope.PERSON })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadConfigsFailure'])
        expect(lemonToast.error).toHaveBeenCalledWith('Failed to load customer profile configs')
    })
})
