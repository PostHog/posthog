import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { initKeaTests } from '~/test/init'

import { customProductsLogic } from './customProductsLogic'
import { MovedItem, projectTreeDataLogic } from './projectTreeDataLogic'

// pluralize() joins the count to the unit with a non-breaking space, which no reader can see in an assertion.
const toastText = (message: unknown): string => String(message).replace(/\u00a0/g, ' ')

describe('projectTreeDataLogic', () => {
    let logic: ReturnType<typeof projectTreeDataLogic.build>
    let unmount: () => void

    beforeEach(async () => {
        jest.restoreAllMocks()
        jest.spyOn(api.fileSystem, 'list').mockResolvedValue({ count: 0, results: [], users: [] })
        jest.spyOn(api.fileSystem, 'unfiled').mockResolvedValue(null)
        jest.spyOn(api.fileSystemShortcuts, 'list').mockResolvedValue({ count: 0, results: [] })

        initKeaTests()
        logic = projectTreeDataLogic()
        unmount = logic.mount()
        await expectLogic(logic).toDispatchActions(['loadUnfiledItemsSuccess'])
        jest.clearAllMocks()
    })

    afterEach(() => {
        unmount?.()
        jest.restoreAllMocks()
    })

    it('shows only the products the user added, with nothing injected alongside them', () => {
        customProductsLogic.actions.loadCustomProductsSuccess([
            {
                id: 'abc',
                product_path: 'Session replay',
                enabled: true,
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-01T00:00:00Z',
            },
        ])

        const paths = logic.values.getCustomProductTreeItems('').map((item) => item.record?.path)

        expect(paths).toEqual(['Session replay'])
    })

    it('handles null unfiled item responses', async () => {
        jest.mocked(api.fileSystem.unfiled).mockResolvedValueOnce(null)

        await expectLogic(logic, () => {
            logic.actions.loadUnfiledItems()
        })
            .toDispatchActions(['loadUnfiledItems', 'loadUnfiledItemsSuccess'])
            .toMatchValues({ unfiledItems: true })

        expect(api.fileSystem.list).not.toHaveBeenCalled()
    })

    it('loads unfiled folders when the count response reports items', async () => {
        logic.actions.createSavedItem({ id: 'saved-insight', path: 'Unfiled/Insights/Saved insight', type: 'insight' })
        jest.mocked(api.fileSystem.unfiled).mockResolvedValueOnce({ count: 1 })

        await expectLogic(logic, () => {
            logic.actions.loadUnfiledItems()
        }).toDispatchActions([
            'loadUnfiledItems',
            ({ type, payload }) => type === logic.actionTypes.loadFolder && payload.folder === 'Unfiled',
            ({ type, payload }) => type === logic.actionTypes.loadFolder && payload.folder === 'Unfiled/Insights',
            'loadUnfiledItemsSuccess',
        ])

        expect(api.fileSystem.list).toHaveBeenCalledWith({
            parent: 'Unfiled',
            depth: 2,
            limit: 101,
            offset: 0,
        })
        expect(api.fileSystem.list).toHaveBeenCalledWith({
            parent: 'Unfiled/Insights',
            depth: 3,
            limit: 101,
            offset: 0,
        })
    })

    it('reports a bulk move once, with an undo that reverts every item', async () => {
        const success = jest.spyOn(lemonToast, 'success').mockReturnValue('' as any)
        const move = jest.spyOn(api.fileSystem, 'move').mockResolvedValue({} as any)
        const items = [
            { id: 'fs-1', type: 'dashboard', path: 'Marketing/A', ref: '1' },
            { id: 'fs-2', type: 'dashboard', path: 'Marketing/B', ref: '2' },
            { id: 'fs-3', type: 'dashboard', path: 'Marketing/C', ref: '3' },
        ]

        await expectLogic(logic, () => {
            logic.actions.moveItems(
                items.map((item) => ({ item: item as any, newPath: `Product/${item.path.slice(-1)}` })),
                true,
                'test'
            )
        })
            // One announcement carrying everything that landed, so a consumer whose work is worth doing once
            // per operation (a refetch) reads the boundary off the action instead of inferring it from a timer.
            .toDispatchActions([
                ({ type, payload }) =>
                    type === logic.actionTypes.movesSettled &&
                    payload.moved.map(({ item }: MovedItem) => item.id).join() === 'fs-1,fs-2,fs-3',
            ])
            .toFinishAllListeners()

        expect(move).toHaveBeenCalledTimes(3)
        // movesSettled rides in the same branch as this toast, so one toast is one announcement.
        expect(success).toHaveBeenCalledTimes(1)
        expect(toastText(success.mock.calls[0][0])).toEqual('Moved 3 items')

        // Undo has to carry the whole batch: the per-item toast it replaced could only revert one item.
        move.mockClear()
        success.mock.calls[0][1]?.button?.action?.()
        await expectLogic(logic).toFinishAllListeners()
        expect(move.mock.calls).toEqual([
            ['fs-1', 'Marketing/A'],
            ['fs-2', 'Marketing/B'],
            ['fs-3', 'Marketing/C'],
        ])
    })

    it('reports a partly failed bulk move as what moved plus what did not', async () => {
        const success = jest.spyOn(lemonToast, 'success').mockReturnValue('' as any)
        const error = jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)
        jest.spyOn(api.fileSystem, 'move')
            .mockResolvedValueOnce({} as any)
            .mockRejectedValueOnce(new Error('nope'))
            .mockRejectedValueOnce(new Error('nope'))
        jest.spyOn(console, 'error').mockReturnValue()

        await expectLogic(logic, () => {
            logic.actions.moveItems(
                [
                    { item: { id: 'fs-1', type: 'dashboard', path: 'Marketing/A' } as any, newPath: 'Product/A' },
                    { item: { id: 'fs-2', type: 'dashboard', path: 'Marketing/B' } as any, newPath: 'Product/B' },
                    { item: { id: 'fs-3', type: 'dashboard', path: 'Marketing/C' } as any, newPath: 'Product/C' },
                ],
                true,
                'test'
            )
        }).toFinishAllListeners()

        expect(toastText(success.mock.calls[0][0])).toEqual('Moved 1 item')
        expect(toastText(error.mock.calls[0][0])).toEqual('Could not move 2 items. Try again.')

        // Undo may only revert what landed. Reverting a failed item would move it away from where it still is.
        const move = jest.mocked(api.fileSystem.move)
        move.mockClear().mockResolvedValue({} as any)
        success.mock.calls[0][1]?.button?.action?.()
        await expectLogic(logic).toFinishAllListeners()
        expect(move.mock.calls).toEqual([['fs-1', 'Marketing/A']])
    })

    it('keeps the underlying error on a single failed move', async () => {
        const error = jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)
        jest.spyOn(api.fileSystem, 'move').mockRejectedValue(new Error('nope'))
        jest.spyOn(console, 'error').mockReturnValue()

        await expectLogic(logic, () => {
            logic.actions.moveItem(
                { id: 'fs-1', type: 'dashboard', path: 'Marketing/A' } as any,
                'Product/A',
                true,
                'test'
            )
        }).toFinishAllListeners()

        expect(error).toHaveBeenCalledWith('Error moving item: Error: nope')
    })

    it('deleteSavedItem does not crash when the parent folder is not loaded (lazy store)', () => {
        // Folders load lazily; deleting an item whose parent folder was never loaded must not throw on
        // state[folder].filter (previously "Cannot read properties of undefined (reading 'filter')").
        expect(() =>
            logic.actions.deleteSavedItem({ id: 'fs-x', type: 'dashboard', path: 'Marketing/Q1/X', ref: '9' } as any)
        ).not.toThrow()
    })
})
