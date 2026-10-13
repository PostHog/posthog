import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { reportsLogic } from './reportsLogic'

describe('shared team folder context', () => {
    it('shows loaded root folders and files without requiring a tree folder to be expanded', async () => {
        useMocks({
            get: {
                '/api/environments/:team/file_system/': [
                    200,
                    {
                        users: [],
                        results: [
                            { id: 'sales', type: 'folder', path: 'Sales' },
                            { id: 'root-dashboard', type: 'dashboard', path: 'Company overview', ref: '42' },
                            { id: 'nested-dashboard', type: 'dashboard', path: 'Sales/Weekly review', ref: '43' },
                        ],
                    },
                ],
            },
        })
        initKeaTests()
        const logic = reportsLogic({ folder: '' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.folderEntries.map((entry) => entry.id)).toEqual(['sales'])
        expect(logic.values.fileEntries.map((entry) => entry.id)).toEqual(['root-dashboard'])
    })
    it('creates a named team folder with a shared description and starting dashboard', async () => {
        const requests: Record<string, unknown>[] = []
        const environments: string[] = []
        useMocks({
            get: { '/api/environments/:team/file_system/': [200, { results: [], users: [] }] },
            post: {
                '/api/projects/:project/file_system/': async ({ request, params }) => {
                    environments.push(String(params.project))
                    const data = (await request.json()) as Record<string, unknown>
                    requests.push(data)
                    return [201, { id: 'new-folder', ...data }]
                },
            },
        })
        initKeaTests(true, MOCK_DEFAULT_TEAM, { ...MOCK_DEFAULT_PROJECT, id: 12345 })
        const logic = reportsLogic({ folder: '' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.openFolderSetup()
            logic.actions.setFolderFormValues({
                name: 'Growth / PLG',
                description: 'Activation and retention',
                dashboardId: 42,
            })
            logic.actions.submitFolderForm()
        }).toFinishAllListeners()

        expect(requests).toEqual([
            {
                path: 'Growth \\/ PLG',
                type: 'folder',
                meta: {
                    custom_dashboards: {
                        team_folder: true,
                        description: 'Activation and retention',
                        pinned_dashboard_id: 42,
                    },
                },
            },
        ])
        expect(router.values.searchParams.folder).toBe('Growth \\/ PLG')
        expect(environments).toEqual([String(MOCK_DEFAULT_TEAM.id)])
    })

    it('pins once on the shared folder and preserves its description and other metadata', async () => {
        let meta = {
            existing: 'keep',
            custom_dashboards: {
                team_folder: true,
                description: 'Weekly review',
                pinned_dashboard_id: null as number | null,
            },
        }
        const requests: Record<string, unknown>[] = []
        useMocks({
            get: {
                '/api/environments/:team/file_system/': ({ request }) => {
                    const parent = new URL(request.url).searchParams.get('parent')
                    const offset = Number(new URL(request.url).searchParams.get('offset') ?? 0)
                    const folders = [
                        ...Array.from({ length: 100 }, (_, index) => ({
                            id: `folder-${index}`,
                            type: 'folder',
                            path: `Folder ${index}`,
                        })),
                        { id: 'sales', type: 'folder', path: 'Sales', meta },
                    ]
                    return [200, { results: parent ? [] : folders.slice(offset, offset + 101), users: [] }]
                },
            },
            patch: {
                '/api/projects/:project/file_system/sales/': async ({ request }) => {
                    const data = (await request.json()) as { meta: typeof meta }
                    requests.push(data)
                    meta = data.meta
                    return [200, { id: 'sales', type: 'folder', path: 'Sales', meta }]
                },
            },
        })
        initKeaTests()
        const logic = reportsLogic({ folder: 'Sales' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.pinDashboard(42)
            logic.actions.pinDashboard(42)
        }).toFinishAllListeners()

        expect(requests).toEqual([
            {
                meta: {
                    existing: 'keep',
                    custom_dashboards: { team_folder: true, description: 'Weekly review', pinned_dashboard_id: 42 },
                },
            },
        ])
        expect(logic.values.folderContext.pinned_dashboard_id).toBe(42)
    })
})

describe('creating a report in a folder', () => {
    it('creates one dashboard in the current folder without changing Home', async () => {
        const requests: Record<string, unknown>[] = []
        useMocks({
            post: {
                '/api/environments/:team/dashboards/': async ({ request }) => {
                    requests.push((await request.json()) as Record<string, unknown>)
                    return [201, { id: 123, name: 'New dashboard' }]
                },
            },
        })
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, home_tab_dashboard: 42 })
        const dashboardLogic = newDashboardLogic()
        dashboardLogic.mount()
        dashboardLogic.actions.setAsHomeTabDashboardAfterCreation(true)
        const logic = reportsLogic({ folder: 'Sales/Quarter 1' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.createDashboard()
            logic.actions.createDashboard()
        }).toFinishAllListeners()

        expect(requests).toEqual([
            expect.objectContaining({ _create_in_folder: 'Sales/Quarter 1', name: 'New dashboard' }),
        ])
        expect(teamLogic.values.currentTeam?.home_tab_dashboard).toBe(42)
    })
})
