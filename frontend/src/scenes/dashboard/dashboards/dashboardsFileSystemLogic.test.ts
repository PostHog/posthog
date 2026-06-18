import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { useMocks } from '~/mocks/jest'
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
        jest.spyOn(api.fileSystem, 'list').mockResolvedValue({
            count: 1,
            results: [{ id: 'fs-1', type: 'dashboard', ref: '1', path: 'Marketing/A' }],
            users: [],
        } as any)
        jest.spyOn(api.fileSystem, 'unfiled').mockResolvedValue(null as any)
        jest.spyOn(api.fileSystemShortcuts, 'list').mockResolvedValue({ count: 0, results: [] } as any)
        initKeaTests()
        logic = dashboardsFileSystemLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
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
})
