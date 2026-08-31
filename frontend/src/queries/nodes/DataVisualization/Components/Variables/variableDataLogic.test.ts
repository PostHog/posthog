import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

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

    it('keeps the existing variables when the list fetch fails', async () => {
        // A transient gateway failure must degrade to the current list, not escape into error tracking.
        jest.mocked(api.insightVariables.list).mockRejectedValue(new Error('Non-OK response'))
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadVariablesSuccess'])
        expect(logic.values.variables).toEqual([])
    })
})
