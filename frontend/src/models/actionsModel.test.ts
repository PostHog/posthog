import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { refreshMountedActions, actionsModel } from './actionsModel'

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

    it('clears loaded actions when the current team changes', async () => {
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadActionsSuccess'])

        logic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 2 })

        expect(logic.values.actions).toEqual([])
        expect(logic.values.actionsLoaded).toBe(false)
    })

    it('refreshes every mounted actions cache after an action mutation', async () => {
        const lazyLogic = actionsModel({ skipLoad: true })
        logic.mount()
        lazyLogic.mount()
        await expectLogic(logic).toDispatchActions(['loadActionsSuccess'])
        lazyLogic.actions.loadActions()
        await expectLogic(lazyLogic).toDispatchActions(['loadActionsSuccess'])

        refreshMountedActions()

        await expectLogic(logic).toDispatchActions(['loadActionsSuccess'])
        await expectLogic(lazyLogic).toDispatchActions(['loadActionsSuccess'])
        expect(requestCount).toBe(4)
    })
})
