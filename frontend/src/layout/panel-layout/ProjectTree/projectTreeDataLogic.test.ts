import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { projectTreeDataLogic } from './projectTreeDataLogic'

describe('projectTreeDataLogic', () => {
    let logic: ReturnType<typeof projectTreeDataLogic.build>
    let unmount: () => void

    const shortcuts: FileSystemEntry[] = [
        { id: 'shortcut-1', path: 'Product analytics', type: 'insight', href: '/insights/1', ref: '1' },
        { id: 'shortcut-2', path: 'Session replay', type: 'session_replay', href: '/replay', ref: '2' },
        { id: 'shortcut-3', path: 'Dashboard', type: 'dashboard', href: '/dashboard/3', ref: '3' },
    ]

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

    function seedShortcuts(shortcutData: FileSystemEntry[]): void {
        logic.actions.loadShortcutsSuccess(shortcutData)
    }

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

    it('moves a starred item up by reusing the reorder endpoint', async () => {
        jest.spyOn(api.fileSystemShortcuts, 'reorder').mockResolvedValue(shortcuts)
        seedShortcuts(shortcuts)

        await expectLogic(logic, () => {
            logic.actions.moveShortcutInStarred('shortcut-2', 'up')
        }).toDispatchActions(['moveShortcutInStarred', 'reorderShortcuts', 'reorderShortcutsSuccess'])

        expect(api.fileSystemShortcuts.reorder).toHaveBeenCalledWith(['shortcut-2', 'shortcut-1', 'shortcut-3'])
        expect(logic.values.shortcutData.map((shortcut) => shortcut.id)).toEqual([
            'shortcut-2',
            'shortcut-1',
            'shortcut-3',
        ])
        expect(logic.values.shortcutMoveAvailability.get('shortcut-2')).toEqual({
            canMoveUp: false,
            canMoveDown: true,
        })
    })

    it('does not reorder when the starred item is already at the top', async () => {
        const reorderSpy = jest.spyOn(api.fileSystemShortcuts, 'reorder').mockResolvedValue(shortcuts)
        seedShortcuts(shortcuts)

        await expectLogic(logic, () => {
            logic.actions.moveShortcutInStarred('shortcut-1', 'up')
        }).toDispatchActions(['moveShortcutInStarred'])

        expect(reorderSpy).not.toHaveBeenCalled()
        expect(logic.values.shortcutMoveAvailability.get('shortcut-1')).toEqual({
            canMoveUp: false,
            canMoveDown: true,
        })
    })
})
