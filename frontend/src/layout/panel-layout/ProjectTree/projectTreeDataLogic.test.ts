import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { initKeaTests } from '~/test/init'

import { projectTreeDataLogic } from './projectTreeDataLogic'

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

    it('emits the dashboard-move primary-metric event for dashboards but not for other item types', async () => {
        const eventUsage = eventUsageLogic()
        eventUsage.mount()
        const capture = jest.spyOn(posthog, 'capture').mockReturnValue(undefined as any)
        const move = jest.spyOn(api.fileSystem, 'move')
        move.mockResolvedValueOnce({ id: 'fs-1', type: 'dashboard', path: 'Product/A' } as any)
        move.mockResolvedValueOnce({ id: 'fs-2', type: 'insight', path: 'Product/B' } as any)

        // A dashboard move fires the experiment's primary-metric event after the API move succeeds.
        await expectLogic(eventUsage, () => {
            logic.actions.moveItem(
                { id: 'fs-1', type: 'dashboard', path: 'Unfiled/Dashboards/A', ref: '1' } as any,
                'Product/A',
                true,
                'test'
            )
        }).toDispatchActions(['reportDashboardMovedToFolder'])
        // Coarse fields only — never the folder/dashboard names (Unfiled/Dashboards/A -> Product/A).
        expect(capture).toHaveBeenCalledWith(
            'dashboard moved to folder',
            expect.objectContaining({
                from_depth: 3,
                to_depth: 2,
                moved_from_unfiled: true,
                moved_to_unfiled: false,
            })
        )

        // A non-dashboard move still processes (movedItem) but must NOT fire the dashboard event.
        capture.mockClear()
        await expectLogic(logic, () => {
            logic.actions.moveItem(
                { id: 'fs-2', type: 'insight', path: 'Unfiled/Insights/B', ref: '2' } as any,
                'Product/B',
                true,
                'test'
            )
        }).toDispatchActions(['movedItem'])
        expect(capture.mock.calls.find((call) => call[0] === 'dashboard moved to folder')).toBeUndefined()

        eventUsage.unmount()
    })

    it('serializes queued actions so a folder delete waits for an in-flight move', async () => {
        // Regression: moves and the folder delete used to run as concurrent loaders, so the delete
        // could reach the server before an in-flight "move item out of this folder" finished and
        // cascade-delete the not-yet-moved rows (soft-deleting their backing insights). The queue must
        // run strictly in enqueue order, so the delete only fires once the move has settled.
        let resolveMove: (value: unknown) => void = () => {}
        const move = jest.spyOn(api.fileSystem, 'move').mockReturnValue(
            new Promise((resolve) => {
                resolveMove = resolve
            }) as any
        )
        const del = jest.spyOn(api.fileSystem, 'delete').mockResolvedValue({ deleted: [] } as any)

        logic.actions.queueAction(
            {
                type: 'move',
                item: { id: 'fs-move', type: 'insight', path: 'Unfiled/A', ref: '1' },
                path: 'Unfiled/A',
                newPath: 'Product/A',
            } as any,
            'test'
        )
        logic.actions.queueAction(
            {
                type: 'delete',
                item: { id: 'fs-del', type: 'insight', path: 'Unfiled/B', ref: '2' },
                path: 'Unfiled/B',
            } as any,
            'test'
        )

        // Flush pending microtasks: the move is in flight, but the delete stays blocked behind it.
        await new Promise((resolve) => setTimeout(resolve, 0))
        expect(move).toHaveBeenCalledTimes(1)
        expect(del).not.toHaveBeenCalled()

        // Once the move settles, the delete is released to run.
        resolveMove({ id: 'fs-move', type: 'insight', path: 'Product/A' })
        await new Promise((resolve) => setTimeout(resolve, 0))
        expect(del).toHaveBeenCalledTimes(1)
    })

    it('deleteSavedItem does not crash when the parent folder is not loaded (lazy store)', () => {
        // Folders load lazily; deleting an item whose parent folder was never loaded must not throw on
        // state[folder].filter (previously "Cannot read properties of undefined (reading 'filter')").
        expect(() =>
            logic.actions.deleteSavedItem({ id: 'fs-x', type: 'dashboard', path: 'Marketing/Q1/X', ref: '9' } as any)
        ).not.toThrow()
    })
})
