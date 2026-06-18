import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { initKeaTests } from '~/test/init'

import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'

describe('dashboardsFileSystemLogic', () => {
    let logic: ReturnType<typeof dashboardsFileSystemLogic.build>
    let unmountEventUsage: () => void

    useMocks({
        get: {
            '/api/environments/:team_id/dashboards/': () => [200, { count: 0, results: [], next: null }],
            '/api/projects/:team_id/dashboards/': () => [200, { count: 0, results: [], next: null }],
        },
    })

    beforeEach(() => {
        jest.spyOn(api.fileSystem, 'list').mockResolvedValue({
            count: 1,
            results: [{ id: 'fs-1', type: 'dashboard', ref: '1', path: 'Marketing/A' }],
            users: [],
        } as any)
        jest.spyOn(api.fileSystem, 'unfiled').mockResolvedValue(null as any)
        jest.spyOn(api.fileSystemShortcuts, 'list').mockResolvedValue({ count: 0, results: [] } as any)
        jest.spyOn(api.fileSystem, 'move').mockResolvedValue({
            id: 'fs-1',
            type: 'dashboard',
            ref: '1',
            path: 'Product/A',
        } as any)
        jest.spyOn(api, 'create').mockResolvedValue({ id: 99, name: 'A (Copy)', tiles: [] } as any)
        jest.spyOn(api, 'update').mockResolvedValue({ id: 1, name: 'Renamed', tiles: [] } as any)
        initKeaTests()
        unmountEventUsage = eventUsageLogic.mount()
        logic = dashboardsFileSystemLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        unmountEventUsage?.()
        jest.restoreAllMocks()
    })

    it('toggles folder collapse state independently', async () => {
        await expectLogic(logic, () => logic.actions.toggleFolder('Marketing')).toMatchValues({
            collapsedFolders: { Marketing: true },
        })
        await expectLogic(logic, () => logic.actions.toggleFolder('Marketing')).toMatchValues({
            collapsedFolders: { Marketing: false },
        })
    })

    it('loads dashboard file-system entries indexed by ref', async () => {
        await expectLogic(logic).toDispatchActions(['loadDashboardFileSystemEntriesSuccess'])
        expect(logic.values.entryByRef['1']?.path).toEqual('Marketing/A')
    })

    it('moveDashboardToFolder delegates to projectTreeDataLogic.moveItem', async () => {
        await expectLogic(logic).toDispatchActions(['loadDashboardFileSystemEntriesSuccess'])
        await expectLogic(projectTreeDataLogic, () => {
            logic.actions.moveDashboardToFolder(1, 'Product')
        }).toDispatchActions(['moveItem'])
    })

    it('navigates folders and exposes a breadcrumb', async () => {
        await expectLogic(logic, () => logic.actions.navigateToFolder('Marketing')).toMatchValues({
            currentFolder: 'Marketing',
            breadcrumb: [
                { label: 'All dashboards', path: '' },
                { label: 'Marketing', path: 'Marketing' },
            ],
        })
    })

    it('cut then paste moves the dashboard into the folder and clears the clipboard', async () => {
        await expectLogic(logic).toDispatchActions(['loadDashboardFileSystemEntriesSuccess'])
        logic.actions.cutDashboard(1)
        await expectLogic(logic, () => logic.actions.pasteIntoFolder('Marketing')).toDispatchActions([
            'moveDashboardToFolder',
            'clearClipboard',
        ])
        expect(logic.values.clipboard).toBeNull()
    })

    it('copy then paste duplicates the dashboard', async () => {
        logic.actions.copyDashboard(1)
        await expectLogic(dashboardsModel, () => {
            logic.actions.pasteIntoFolder('Marketing')
        }).toDispatchActions(['duplicateDashboard'])
    })

    it('moveDashboardToFolder warns instead of silently no-op when the dashboard has no FileSystem entry', async () => {
        await expectLogic(logic).toDispatchActions(['loadDashboardFileSystemEntriesSuccess'])
        const warning = jest.spyOn(lemonToast, 'warning').mockReturnValue('' as any)
        logic.actions.moveDashboardToFolder(999, 'Product')
        expect(warning).toHaveBeenCalled()
    })

    it('pasteIntoFolder with an empty clipboard does not move or duplicate', async () => {
        await expectLogic(logic).toDispatchActions(['loadDashboardFileSystemEntriesSuccess'])
        expect(logic.values.clipboard).toBeNull()
        ;(api.fileSystem.move as jest.Mock).mockClear()
        ;(api.create as jest.Mock).mockClear()
        logic.actions.pasteIntoFolder('Marketing')
        await expectLogic(logic).toFinishAllListeners()
        expect(api.fileSystem.move).not.toHaveBeenCalled()
        expect(api.create).not.toHaveBeenCalled()
    })

    it.each([
        ['a new non-empty name', 'New name', true],
        ['an empty/whitespace name', '   ', false],
        ['the unchanged current name', 'A', false],
    ])('renameDashboard dispatches updateDashboard only for %s', async (_description, name, shouldUpdate) => {
        // Seed a dashboard so the same-name guard has a current name ('A') to compare against.
        dashboardsModel.actions.duplicateDashboardSuccess({ id: 1, name: 'A' } as any)
        ;(api.update as jest.Mock).mockClear()
        logic.actions.renameDashboard(1, name)
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(dashboardsModel).toFinishAllListeners()
        expect((api.update as jest.Mock).mock.calls.length > 0).toBe(shouldUpdate)
    })
})
