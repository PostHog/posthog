import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { actionsModel } from './actionsModel'

describe('actionsModel', () => {
    let requestCount: number
    let logic: ReturnType<typeof actionsModel.build>

    beforeEach(() => {
        requestCount = 0
        useMocks({
            get: {
                '/api/projects/:team/actions/': () => {
                    requestCount++
                    return [200, { results: [], count: 0 }]
                },
            },
        })
        initKeaTests()
        logic = actionsModel.build()
    })

    it('reuses actions after a consumer remounts', async () => {
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadActionsSuccess'])

        logic.unmount()
        expect(logic.isMounted()).toBe(true)

        logic.mount()
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(requestCount).toBe(1)
    })
})
