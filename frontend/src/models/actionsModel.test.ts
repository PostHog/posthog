import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ActionType } from '~/types'

import { refreshMountedActions, updateMountedAction, actionsModel } from './actionsModel'

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

    it('updates every mounted actions cache after an action rename', async () => {
        const lazyLogic = actionsModel({ skipLoad: true })
        logic.mount()
        lazyLogic.mount()
        logic.actions.loadActionsSuccess([{ id: 1, name: 'Old name', steps: [] }] as any)
        lazyLogic.actions.loadActionsSuccess([{ id: 1, name: 'Old name', steps: [] }] as any)

        updateMountedAction({ id: 1, name: 'New name', steps: [] } as any)

        expect(logic.values.actions[0].name).toBe('New name')
        expect(lazyLogic.values.actions[0].name).toBe('New name')
    })

    it('deduplicates concurrent non-forced loads', async () => {
        let resolveRequest: (value: { results: ActionType[] }) => void
        let resolveRequestStarted: () => void
        const requestStarted = new Promise<void>((resolve) => {
            resolveRequestStarted = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team/actions/': () =>
                    new Promise<{ results: ActionType[] }>((resolve) => {
                        requestCount++
                        resolveRequest = resolve
                        resolveRequestStarted()
                    }),
            },
        })

        logic.mount()
        logic.actions.loadActions()

        await requestStarted
        expect(requestCount).toBe(1)
        resolveRequest!({ results: [] })
        await expectLogic(logic).toDispatchActions(['loadActionsSuccess'])
    })

    it('preserves an action rename when an older list request resolves', async () => {
        let resolveRequest: (value: { results: ActionType[] }) => void
        let resolveRequestStarted: () => void
        const requestStarted = new Promise<void>((resolve) => {
            resolveRequestStarted = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team/actions/': () =>
                    new Promise<{ results: ActionType[] }>((resolve) => {
                        resolveRequest = resolve
                        resolveRequestStarted()
                    }),
            },
        })

        logic.actions.loadActionsSuccess([{ id: 1, name: 'Old name', steps: [] } as ActionType])
        logic.mount()
        expectLogic(logic).clearHistory()
        logic.actions.loadActions(true)
        await requestStarted
        updateMountedAction({ id: 1, name: 'New name', steps: [] } as ActionType)
        resolveRequest!({ results: [{ id: 1, name: 'Old name', steps: [] } as ActionType] })

        await expectLogic(logic).toDispatchActions(['loadActionsSuccess'])
        expect(logic.values.actions[0].name).toBe('New name')
    })
})
