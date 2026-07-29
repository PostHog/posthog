import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { QuickActionApi } from '../../generated/api.schemas'
import { QuickActionVisibilityEnumApi } from '../../generated/api.schemas'
import { quickActionsLogic } from './quickActionsLogic'

function makeQuickAction(shortId: string, name: string): QuickActionApi {
    return {
        id: `id-${shortId}`,
        short_id: shortId,
        name,
        description: '',
        content: '',
        rich_content: {},
        actions: {},
        visibility: QuickActionVisibilityEnumApi.Team,
        created_at: '2020-01-01T00:00:00Z',
        created_by: { id: 1 } as QuickActionApi['created_by'],
    }
}

function page(results: QuickActionApi[]): Record<string, unknown> {
    return { count: results.length, next: null, previous: null, results }
}

// Lets a test hold an MSW response until it decides the request should resolve.
function deferred(): { promise: Promise<void>; resolve: () => void } {
    let resolve!: () => void
    const promise = new Promise<void>((r) => {
        resolve = r
    })
    return { promise, resolve }
}

const actionA = makeQuickAction('qa-a', 'Action A')
const actionB = makeQuickAction('qa-b', 'Action B')

describe('quickActionsLogic', () => {
    let logic: ReturnType<typeof quickActionsLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/quick_actions/': () => [200, page([actionA, actionB])],
            },
        })
        initKeaTests()
        logic = quickActionsLogic()
        logic.mount()
        // The currentTeamId subscription fires a load on mount; settle it so it can't interfere.
        await expectLogic(logic).toDispatchActions(['loadQuickActionsSuccess'])
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('closes the modal when the save for the open modal succeeds', async () => {
        useMocks({
            patch: {
                '/api/projects/:team_id/conversations/quick_actions/:short_id/': () => [
                    200,
                    { ...actionA, name: 'Action A updated' },
                ],
            },
        })
        logic.actions.openEditModal(actionA)
        await expectLogic(logic, () => {
            logic.actions.saveQuickAction(null)
        }).toDispatchActions(['quickActionSaved', 'closeModal'])
        expect(logic.values.isModalOpen).toBe(false)
        expect(logic.values.quickActions.find((q) => q.short_id === actionA.short_id)?.name).toBe('Action A updated')
    })

    it('does not close a modal reopened for another item when a stale save resolves', async () => {
        const gate = deferred()
        useMocks({
            patch: {
                '/api/projects/:team_id/conversations/quick_actions/:short_id/': async () => {
                    await gate.promise
                    return [200, { ...actionA, name: 'Action A updated' }]
                },
            },
        })
        logic.actions.openEditModal(actionA)
        logic.actions.saveQuickAction(null)
        // The user closes the saving modal and reopens it for another item before the response lands.
        logic.actions.closeModal()
        logic.actions.openEditModal(actionB)
        gate.resolve()
        await expectLogic(logic).toDispatchActions(['quickActionSaved'])
        expect(logic.values.isModalOpen).toBe(true)
        expect(logic.values.editingShortId).toBe(actionB.short_id)
        // The stale save still lands in the list.
        expect(logic.values.quickActions.find((q) => q.short_id === actionA.short_id)?.name).toBe('Action A updated')
    })

    it('does not close a reopened create modal when a stale create resolves', async () => {
        const gate = deferred()
        useMocks({
            post: {
                '/api/projects/:team_id/conversations/quick_actions/': async () => {
                    await gate.promise
                    return [201, makeQuickAction('qa-new', 'First')]
                },
            },
        })
        logic.actions.openCreateModal()
        logic.actions.setName('First')
        logic.actions.saveQuickAction(null)
        logic.actions.closeModal()
        logic.actions.openCreateModal()
        logic.actions.setName('Second')
        gate.resolve()
        await expectLogic(logic).toDispatchActions(['quickActionSaved'])
        expect(logic.values.isModalOpen).toBe(true)
        expect(logic.values.name).toBe('Second')
    })

    it('fires a single DELETE when the delete action is dispatched twice in quick succession', async () => {
        const gate = deferred()
        let deleteCount = 0
        useMocks({
            delete: {
                '/api/projects/:team_id/conversations/quick_actions/:short_id/': async () => {
                    deleteCount += 1
                    await gate.promise
                    return [204]
                },
            },
        })
        // A double click on the confirm button dispatches the action twice before the first resolves.
        logic.actions.deleteQuickAction(actionA.short_id)
        logic.actions.deleteQuickAction(actionA.short_id)
        gate.resolve()
        await expectLogic(logic).toDispatchActions(['quickActionDeleted']).toFinishAllListeners()
        expect(deleteCount).toBe(1)
        expect(logic.values.quickActions.some((q) => q.short_id === actionA.short_id)).toBe(false)
    })

    it('drops a superseded load instead of clobbering the newer result', async () => {
        const firstRequestStarted = deferred()
        const gate = deferred()
        let requestCount = 0
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/quick_actions/': async () => {
                    requestCount += 1
                    if (requestCount === 1) {
                        firstRequestStarted.resolve()
                        await gate.promise
                        return [200, page([actionA])]
                    }
                    return [200, page([actionB])]
                },
            },
        })
        logic.actions.loadQuickActions()
        await firstRequestStarted.promise
        logic.actions.loadQuickActions()
        await expectLogic(logic).toDispatchActions(['loadQuickActionsSuccess'])
        // The first, superseded request resolves last; its breakpoint must discard it.
        gate.resolve()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.quickActions).toEqual([actionB])
    })
})
