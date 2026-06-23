import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { initKeaTests } from '~/test/init'

import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'

describe('dashboardsFileSystemLogic', () => {
    let logic: ReturnType<typeof dashboardsFileSystemLogic.build>

    useMocks({
        get: {
            '/api/environments/:team_id/dashboards/': () => [200, { count: 0, results: [], next: null }],
            '/api/projects/:team_id/dashboards/': () => [200, { count: 0, results: [], next: null }],
        },
    })

    beforeEach(() => {
        jest.spyOn(api.fileSystem, 'list').mockImplementation(
            async ({ type }: { type?: string } = {}) =>
                (type === 'folder'
                    ? { count: 0, results: [], users: [] }
                    : {
                          count: 1,
                          results: [{ id: 'fs-1', type: 'dashboard', ref: '1', path: 'Marketing/A' }],
                          users: [],
                      }) as any
        )
        jest.spyOn(api.fileSystem, 'unfiled').mockResolvedValue(null as any)
        jest.spyOn(api.fileSystemShortcuts, 'list').mockResolvedValue({ count: 0, results: [] } as any)
        jest.spyOn(api.fileSystem, 'create').mockResolvedValue({ id: 'fs-new', type: 'folder', path: 'x' } as any)
        initKeaTests()
        logic = dashboardsFileSystemLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('loads dashboard file-system entries indexed by ref', async () => {
        await expectLogic(logic).toDispatchActions(['loadDashboardFileSystemEntriesSuccess'])
        expect(logic.values.entryByRef['1']?.path).toEqual('Marketing/A')
    })

    it('exposes empty folder rows in the folder tree', async () => {
        ;(api.fileSystem.list as jest.Mock).mockImplementation(
            async ({ type }: { type?: string } = {}) =>
                (type === 'folder'
                    ? { count: 1, results: [{ id: 'fld', type: 'folder', path: 'Ideas' }], users: [] }
                    : { count: 0, results: [], users: [] }) as any
        )
        logic.unmount()
        logic = dashboardsFileSystemLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadDashboardFileSystemEntriesSuccess',
            'loadFolderEntriesSuccess',
        ])
        // The folder rows feed the tree even with no dashboards beneath them (empty folders appear).
        expect(logic.values.folderTree.map((node) => node.path)).toEqual(['Ideas'])
    })

    it('navigates folders', async () => {
        await expectLogic(logic, () => logic.actions.navigateToFolder('Marketing')).toMatchValues({
            currentFolder: 'Marketing',
        })
        await expectLogic(logic, () => logic.actions.navigateToFolder('')).toMatchValues({ currentFolder: '' })
    })

    it('refetches entries when a dashboard move lands so the subtree reflects the new path', async () => {
        await expectLogic(logic).toDispatchActions(['loadDashboardFileSystemEntriesSuccess'])
        expect(logic.values.entryByRef['1']?.path).toEqual('Marketing/A')
        ;(api.fileSystem.list as jest.Mock).mockImplementation(
            async ({ type }: { type?: string } = {}) =>
                (type === 'folder'
                    ? { count: 0, results: [], users: [] }
                    : {
                          count: 1,
                          results: [{ id: 'fs-1', type: 'dashboard', ref: '1', path: 'Product/A' }],
                          users: [],
                      }) as any
        )
        await expectLogic(logic, () => {
            projectTreeDataLogic.actions.movedItem(
                { id: 'fs-1', type: 'dashboard', ref: '1', path: 'Marketing/A' } as any,
                'Marketing/A',
                'Product/A'
            )
        }).toDispatchActions(['loadDashboardFileSystemEntries', 'loadDashboardFileSystemEntriesSuccess'])
        expect(logic.values.entryByRef['1']?.path).toEqual('Product/A')
    })

    it('ignores moves of non-dashboard, non-folder items (no wasted refetch)', async () => {
        await expectLogic(logic).toDispatchActions([
            'loadDashboardFileSystemEntriesSuccess',
            'loadFolderEntriesSuccess',
        ])
        ;(api.fileSystem.list as jest.Mock).mockClear()
        projectTreeDataLogic.actions.movedItem({ id: 'i-1', type: 'insight', path: 'a' } as any, 'a', 'b')
        await expectLogic(logic).toFinishAllListeners()
        expect(api.fileSystem.list).not.toHaveBeenCalled()
    })

    it('refetches the subtree after a duplicate lands', async () => {
        await expectLogic(logic).toDispatchActions(['loadDashboardFileSystemEntriesSuccess'])
        await expectLogic(logic, () => {
            dashboardsModel.actions.duplicateDashboardSuccess({ id: 2, name: 'A (Copy)' } as any)
        }).toDispatchActions(['loadDashboardFileSystemEntries'])
    })

    it('createFolder creates a folder under the current folder, syncs the sidebar, refetches, and selects it', async () => {
        await expectLogic(logic).toDispatchActions(['loadDashboardFileSystemEntriesSuccess'])
        logic.actions.navigateToFolder('Marketing')
        ;(api.fileSystem.create as jest.Mock).mockClear()
        await expectLogic(logic, () => logic.actions.createFolder('Ideas')).toDispatchActions([
            'createFolder',
            // Syncs the sidebar's shared store, then refreshes our own folder rows.
            'createSavedItem',
            'loadFolderEntries',
        ])
        expect(api.fileSystem.create).toHaveBeenCalledWith({ type: 'folder', path: 'Marketing/Ideas' })
        expect(logic.values.currentFolder).toEqual('Marketing/Ideas')
    })

    it('createFolder ignores a blank name', async () => {
        ;(api.fileSystem.create as jest.Mock).mockClear()
        logic.actions.createFolder('   ')
        await expectLogic(logic).toFinishAllListeners()
        expect(api.fileSystem.create).not.toHaveBeenCalled()
    })

    it('toasts an error when loading dashboard folders fails', async () => {
        await expectLogic(logic).toDispatchActions(['loadDashboardFileSystemEntriesSuccess'])
        const error = jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)
        ;(api.fileSystem.list as jest.Mock).mockRejectedValueOnce(new Error('boom'))
        await expectLogic(logic, () => {
            logic.actions.loadDashboardFileSystemEntries()
        }).toDispatchActions(['loadDashboardFileSystemEntriesFailure'])
        expect(error).toHaveBeenCalled()
    })

    it('toasts an error when loading folder rows fails', async () => {
        await expectLogic(logic).toDispatchActions(['loadFolderEntriesSuccess'])
        const error = jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)
        ;(api.fileSystem.list as jest.Mock).mockRejectedValueOnce(new Error('boom'))
        await expectLogic(logic, () => {
            logic.actions.loadFolderEntries()
        }).toDispatchActions(['loadFolderEntriesFailure'])
        expect(error).toHaveBeenCalled()
    })
})
