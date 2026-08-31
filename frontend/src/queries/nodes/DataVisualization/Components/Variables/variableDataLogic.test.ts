import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { variableDataLogic } from './variableDataLogic'

jest.mock('lib/api')

describe('variableDataLogic', () => {
    let logic: ReturnType<typeof variableDataLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = variableDataLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('keeps the existing variables when a transient gateway failure interrupts the fetch', async () => {
        // A 502/503/504 blip must degrade to the current list, not escape into error tracking.
        jest.mocked(api.insightVariables.list).mockRejectedValue(new ApiError('Service unavailable', 503))
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadVariablesSuccess'])
        expect(logic.values.variables).toEqual([])
    })

    it('fails the load when the fetch returns a real error', async () => {
        // A plain 500 is a genuine backend defect, so the load must fail and reach error tracking
        // rather than resolve as an empty success that hides it.
        jest.mocked(api.insightVariables.list).mockRejectedValue(new ApiError('Server error', 500))
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadVariablesFailure']).toNotHaveDispatchedActions(['loadVariablesSuccess'])
        expect(logic.values.variables).toEqual([])
    })
})
