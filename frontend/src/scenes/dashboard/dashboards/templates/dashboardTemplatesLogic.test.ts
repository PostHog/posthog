import { MOCK_DEFAULT_USER, MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import type { DashboardTemplateListParams, DashboardTemplateType } from '~/types'

import { dashboardTemplatesLogic } from './dashboardTemplatesLogic'

jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    userHasAccess: jest.fn(() => true),
}))

describe('dashboardTemplatesLogic', () => {
    let logic: ReturnType<typeof dashboardTemplatesLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        jest.spyOn(api.dashboardTemplates, 'list').mockResolvedValue({ results: [] })
        // `restoreAllMocks` does not reset a `jest.mock` factory's `jest.fn`, so a return value set in one test would
        // leak into the next.
        jest.mocked(userHasAccess).mockReturnValue(true)
        logic = undefined
    })

    afterEach(() => {
        logic?.unmount()
        logic = undefined
        jest.restoreAllMocks()
        resumeKeaLoadersErrors()
    })

    it.each([
        {
            label: 'passes is_featured when listQuery requests featured templates',
            listQuery: { is_featured: true } as const,
            assert: (listMock: jest.Mock) => {
                expect(
                    listMock.mock.calls.some(([params]: [DashboardTemplateListParams]) => params.is_featured === true)
                ).toBe(true)
            },
        },
        {
            label: 'does not set is_featured on the default list query',
            listQuery: undefined,
            assert: (listMock: jest.Mock) => {
                expect(listMock).toHaveBeenCalled()
                expect(
                    listMock.mock.calls.every(
                        ([params]: [DashboardTemplateListParams]) => params.is_featured === undefined
                    )
                ).toBe(true)
            },
        },
    ])('$label', async ({ listQuery, assert }) => {
        const listMock = api.dashboardTemplates.list as jest.Mock
        const mounted = dashboardTemplatesLogic({ scope: 'default', ...(listQuery ? { listQuery } : {}) })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted, () => mounted.actions.getAllTemplates()).toFinishAllListeners()

        assert(listMock)
    })

    it.each([
        {
            label: 'featured: omits search even when filter is long',
            listQuery: { is_featured: true } as const,
            expectedParams: (params: DashboardTemplateListParams) =>
                params.is_featured === true && params.search === undefined,
        },
        {
            label: 'non-featured: passes search when filter is long',
            listQuery: undefined,
            expectedParams: (params: DashboardTemplateListParams) =>
                params.is_featured === undefined && params.search === 'needle',
        },
    ])('$label', async ({ listQuery, expectedParams }) => {
        const listMock = api.dashboardTemplates.list as jest.Mock
        const mounted = dashboardTemplatesLogic({ scope: 'default', ...(listQuery ? { listQuery } : {}) })
        logic = mounted
        mounted.mount()
        mounted.actions.setTemplateFilter('needle')

        await expectLogic(mounted, () => mounted.actions.getAllTemplates()).toFinishAllListeners()

        expect(listMock.mock.calls.some(([params]: [DashboardTemplateListParams]) => expectedParams(params))).toBe(true)
    })

    it.each([
        { visibility: 'official' as const, expectedScope: 'global' },
        { visibility: 'project' as const, expectedScope: 'team' },
        { visibility: 'organization' as const, expectedScope: 'organization' },
        { visibility: 'all' as const, expectedScope: undefined },
    ])(
        'templates tab visibility "$visibility" maps to list scope "$expectedScope"',
        async ({ visibility, expectedScope }) => {
            const listMock = api.dashboardTemplates.list as jest.Mock
            const mounted = dashboardTemplatesLogic({ scope: 'default', templatesTabList: true })
            logic = mounted
            mounted.mount()

            await expectLogic(mounted, () =>
                mounted.actions.setTemplatesTabVisibility(visibility)
            ).toFinishAllListeners()

            expect(
                listMock.mock.calls.some(([params]: [DashboardTemplateListParams]) => params.scope === expectedScope)
            ).toBe(true)
        }
    )

    it.each([
        { filter: 'ch', expected: null },
        { filter: 'churn', expected: 'churn' },
    ])('searches for "$filter" only from three characters (search text: $expected)', async ({ filter, expected }) => {
        const mounted = dashboardTemplatesLogic({ scope: 'default', templatesTabList: true })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted, () => mounted.actions.setTemplateFilter(filter)).toMatchValues({
            searchText: expected,
        })
    })

    // The default test user is staff, so the cases above cover the staff list, official templates included.
    it("lists only this project's and the organization's templates for customers, without official ones", async () => {
        userLogic.mount()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: false })
        const teamTemplate = {
            id: 'team-b',
            template_name: 'B team',
            tiles: [],
            scope: 'team',
        } as DashboardTemplateType
        const organizationTemplate = {
            id: 'org-a',
            template_name: 'A organization',
            tiles: [],
            scope: 'organization',
        } as DashboardTemplateType
        const listMock = (api.dashboardTemplates.list as jest.Mock).mockImplementation(
            async (params: DashboardTemplateListParams) => ({
                results:
                    params.scope === 'team'
                        ? [teamTemplate]
                        : params.scope === 'organization'
                          ? [organizationTemplate]
                          : [],
            })
        )
        const mounted = dashboardTemplatesLogic({ scope: 'default', templatesTabList: true })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted, () => mounted.actions.getAllTemplates())
            .toFinishAllListeners()
            .toMatchValues({ allTemplates: [organizationTemplate, teamTemplate] })

        const requestedScopes = listMock.mock.calls.map(([params]: [DashboardTemplateListParams]) => params.scope)
        expect(new Set(requestedScopes)).toEqual(new Set(['team', 'organization']))
    })

    it.each([
        {
            label: 'staff on an official template',
            isStaff: true,
            canEditDashboards: true,
            template: { scope: 'global', team_id: null },
            canManage: true,
            managedInAnotherProject: false,
            canEditTemplates: true,
        },
        {
            label: 'an editor on a team template',
            isStaff: false,
            canEditDashboards: true,
            template: { scope: 'team', team_id: MOCK_TEAM_ID },
            canManage: true,
            managedInAnotherProject: false,
            canEditTemplates: true,
        },
        {
            label: "an editor on this project's organization template",
            isStaff: false,
            canEditDashboards: true,
            template: { scope: 'organization', team_id: MOCK_TEAM_ID },
            canManage: true,
            managedInAnotherProject: false,
            canEditTemplates: true,
        },
        {
            label: "an editor on another project's organization template",
            isStaff: false,
            canEditDashboards: true,
            template: { scope: 'organization', team_id: MOCK_TEAM_ID + 1 },
            canManage: false,
            managedInAnotherProject: true,
            canEditTemplates: true,
        },
        {
            label: 'an editor on an organization template with no owning project',
            isStaff: false,
            canEditDashboards: true,
            template: { scope: 'organization', team_id: null },
            canManage: false,
            managedInAnotherProject: true,
            canEditTemplates: true,
        },
        {
            label: 'a viewer without editor access on a team template',
            isStaff: false,
            canEditDashboards: false,
            template: { scope: 'team', team_id: MOCK_TEAM_ID },
            canManage: false,
            managedInAnotherProject: false,
            canEditTemplates: false,
        },
    ])(
        '$label: can manage $canManage, managed in another project $managedInAnotherProject, can edit templates $canEditTemplates',
        ({ isStaff, canEditDashboards, template, canManage, managedInAnotherProject, canEditTemplates }) => {
            jest.mocked(userHasAccess).mockReturnValue(canEditDashboards)
            userLogic.mount()
            userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: isStaff })
            const mounted = dashboardTemplatesLogic({ scope: 'default', templatesTabList: true })
            logic = mounted
            mounted.mount()
            const record = {
                id: 'template-1',
                template_name: 'Weekly KPIs',
                tiles: [],
                ...template,
            } as DashboardTemplateType

            expect(mounted.values.canManageTemplate(record)).toBe(canManage)
            expect(mounted.values.isManagedInAnotherProject(record)).toBe(managedInAnotherProject)
            expect(mounted.values.canEditTemplates).toBe(canEditTemplates)
        }
    )

    it('flags a failed load until a reload succeeds, so an error does not read as an empty list', async () => {
        silenceKeaLoadersErrors()
        const listMock = (api.dashboardTemplates.list as jest.Mock).mockRejectedValueOnce(new Error('Network error'))
        const mounted = dashboardTemplatesLogic({ scope: 'default', templatesTabList: true })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted, () => mounted.actions.getAllTemplates())
            .toDispatchActions(['getAllTemplatesFailure'])
            .toMatchValues({ allTemplatesLoadFailed: true })

        listMock.mockResolvedValueOnce({ results: [] })
        await expectLogic(mounted, () => mounted.actions.getAllTemplates())
            .toDispatchActions(['getAllTemplatesSuccess'])
            .toMatchValues({ allTemplatesLoadFailed: false })
    })

    it('clears the search and the visibility filter, removes the search from the URL, and reloads', async () => {
        router.actions.push('/dashboard', { templates: '1', templateFilter: 'churn' })
        const listMock = api.dashboardTemplates.list as jest.Mock
        const mounted = dashboardTemplatesLogic({ scope: 'default', templatesTabList: true })
        logic = mounted
        mounted.mount()
        mounted.actions.setTemplatesTabVisibility('project')
        await expectLogic(mounted).toFinishAllListeners().toMatchValues({ hasActiveFilters: true })

        await expectLogic(mounted, () => mounted.actions.clearFilters())
            .toFinishAllListeners()
            .toMatchValues({ templateFilter: '', templatesTabVisibility: 'all', hasActiveFilters: false })

        expect(router.values.searchParams).not.toHaveProperty('templateFilter')
        expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ scope: undefined, search: undefined }))
    })

    it('clears the template search when the dashboard list URL no longer includes a search (stale query no longer hides templates)', async () => {
        router.actions.push('/dashboard', { templateFilter: 'needle' })
        const mounted = dashboardTemplatesLogic({ scope: 'default' })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted).toMatchValues({ templateFilter: 'needle' })

        router.actions.push('/dashboard', {})

        await expectLogic(mounted).toMatchValues({ templateFilter: '' })
    })

    it('does not redundantly refresh the template catalog when the dashboard URL already matches the current search (no flicker on open)', async () => {
        router.actions.push('/dashboard', {})
        const listMock = api.dashboardTemplates.list as jest.Mock
        const mounted = dashboardTemplatesLogic({ scope: 'default' })
        logic = mounted
        const setTemplateFilterSpy = jest.spyOn(mounted.actions, 'setTemplateFilter')
        mounted.mount()

        await expectLogic(mounted).toFinishAllListeners()

        const listCallsAfterOpen = listMock.mock.calls.length
        expect(setTemplateFilterSpy).not.toHaveBeenCalled()

        await new Promise((resolve) => setTimeout(resolve, 500))

        expect(listMock.mock.calls.length).toBe(listCallsAfterOpen)
    })

    it('still loads the template catalog when the dashboard list opens with no URL search and the catalog has not been fetched yet', async () => {
        router.actions.push('/dashboard', {})
        const listMock = api.dashboardTemplates.list as jest.Mock
        const stub: Pick<DashboardTemplateType, 'id'> = { id: '1' }
        listMock.mockResolvedValue({ results: [stub as DashboardTemplateType] })
        const mounted = dashboardTemplatesLogic({ scope: 'default' })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted).toFinishAllListeners()

        expect(listMock).toHaveBeenCalled()
    })
})
