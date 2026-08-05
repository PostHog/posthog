import { expectLogic } from 'kea-test-utils'

import api, { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'

import { Variable } from '../../types'
import { variableDataLogic } from './variableDataLogic'

const variable = { id: 'variable-1', name: 'My variable' } as unknown as Variable

describe('variableDataLogic', () => {
    let logic: ReturnType<typeof variableDataLogic.build>

    beforeEach(() => {
        initKeaTests(false)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('does not load variables on mount before the current team ID is known', async () => {
        jest.spyOn(ApiConfig, 'hasCurrentTeamId').mockReturnValue(false)
        const listVariables = jest.spyOn(api.insightVariables, 'list').mockResolvedValue({
            results: [variable],
        })

        logic = variableDataLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadVariablesSuccess']).toMatchValues({ variables: [] })
        expect(listVariables).not.toHaveBeenCalled()
    })

    it('loads variables once the current team ID is known', async () => {
        jest.spyOn(ApiConfig, 'hasCurrentTeamId').mockReturnValue(true)
        const listVariables = jest.spyOn(api.insightVariables, 'list').mockResolvedValue({
            results: [variable],
        })

        logic = variableDataLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadVariablesSuccess'])
            .toMatchValues({ variables: [variable] })
        expect(listVariables).toHaveBeenCalled()
    })
})
