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

    it('keeps the existing variables when an empty-bodied transient gateway blip interrupts the fetch', async () => {
        // An empty-bodied 502/503/504 must degrade to the current list, not escape into error tracking.
        jest.mocked(api.insightVariables.list).mockRejectedValue(new ApiError('Service unavailable', 503))
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadVariablesSuccess'])
        expect(logic.values.variables).toEqual([])
    })

    it.each([
        // A plain 500 is a genuine backend defect that must reach error tracking.
        ['a real backend error', new ApiError('Server error', 500)],
        // A transient status that carries a message must surface it rather than degrade silently.
        [
            'a transient failure with a detail message',
            new ApiError('Service unavailable', 503, undefined, { detail: 'Scheduled maintenance' }),
        ],
    ])('fails the load for %s rather than hiding it as an empty success', async (_, error) => {
        jest.mocked(api.insightVariables.list).mockRejectedValue(error)
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadVariablesFailure'])
            .toNotHaveDispatchedActions(['loadVariablesSuccess'])
        expect(logic.values.variables).toEqual([])
    })
})
