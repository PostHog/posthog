import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api, { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { DashboardsTab } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import type { DashboardTemplateType } from '~/types'

import { dashboardTemplateCopyLogic } from './dashboardTemplateCopyLogic'
import { dashboardTemplatesLogic } from './dashboardTemplatesLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

describe('dashboardTemplateCopyLogic', () => {
    let logic: ReturnType<typeof dashboardTemplateCopyLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
        logic = undefined
        jest.spyOn(api.dashboardTemplates, 'get').mockResolvedValue({
            id: 'tpl-1',
            template_name: 'Source template',
        } as DashboardTemplateType)
        jest.spyOn(api.dashboardTemplates, 'copyBetweenProjects').mockResolvedValue({
            id: 'tpl-2',
            template_name: 'Source template (copy)',
        } as DashboardTemplateType)
        jest.spyOn(router.actions, 'push')
        jest.spyOn(router.actions, 'replace')
        jest.spyOn(dashboardTemplatesLogic, 'findMounted').mockReturnValue({
            actions: { getAllTemplates: jest.fn() },
        } as unknown as ReturnType<typeof dashboardTemplatesLogic.findMounted>)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('loads source template with explicit sourceTeamId for the API project', async () => {
        const getMock = api.dashboardTemplates.get as jest.Mock
        const mounted = dashboardTemplateCopyLogic({ sourceTemplateId: 'abc', sourceTeamId: 99 })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted).toFinishAllListeners()

        expect(getMock).toHaveBeenCalledWith('abc', 99)
    })

    it('loads source template using currentTeamId when sourceTeamId is omitted', async () => {
        const getMock = api.dashboardTemplates.get as jest.Mock
        const mounted = dashboardTemplateCopyLogic({ sourceTemplateId: 'legacy-url' })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted).toFinishAllListeners()

        expect(getMock).toHaveBeenCalledWith('legacy-url', MOCK_TEAM_ID)
    })

    it('canonicalizes URL when sourceTeamId is omitted', async () => {
        const mounted = dashboardTemplateCopyLogic({ sourceTemplateId: 'no-query-team' })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted).toFinishAllListeners()

        expect(router.actions.replace).toHaveBeenCalledWith(
            urls.dashboardTemplateCopyToProject('no-query-team', MOCK_TEAM_ID)
        )
    })

    it('marks load failed when fetching the source template errors', async () => {
        const getMock = api.dashboardTemplates.get as jest.Mock
        getMock.mockRejectedValueOnce(new Error('not found'))

        const mounted = dashboardTemplateCopyLogic({ sourceTemplateId: 'missing', sourceTeamId: 1 })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted).toFinishAllListeners()

        expect(mounted.values.sourceTemplateLoadFailed).toBe(true)
    })

    it('on successful copy toast includes destination project name when org lists it', async () => {
        const destinationTeam = { ...MOCK_DEFAULT_TEAM, id: 1002, name: 'Beta project', uuid: 'beta-uuid-0001' }
        const orgWithTwoTeams = {
            ...MOCK_DEFAULT_ORGANIZATION,
            teams: [MOCK_DEFAULT_TEAM, destinationTeam],
        }
        initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, orgWithTwoTeams)

        const getAllTemplates = jest.fn()
        ;(dashboardTemplatesLogic.findMounted as jest.Mock).mockReturnValue({
            actions: { getAllTemplates },
        })

        const mounted = dashboardTemplateCopyLogic({ sourceTemplateId: 'src-1', sourceTeamId: 1 })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted).toFinishAllListeners()

        mounted.actions.setDestinationTeamId(destinationTeam.id)
        await expectLogic(mounted, () => mounted.actions.submitCopy()).toFinishAllListeners()

        expect(lemonToast.success).toHaveBeenCalledWith('Copied to Beta project', {
            button: expect.objectContaining({
                label: 'Open project',
                action: expect.any(Function),
            }),
        })
    })

    it('on successful copy refreshes templates, toasts, and navigates to the templates tab', async () => {
        const getAllTemplates = jest.fn()
        ;(dashboardTemplatesLogic.findMounted as jest.Mock).mockReturnValue({
            actions: { getAllTemplates },
        })

        const mounted = dashboardTemplateCopyLogic({ sourceTemplateId: 'src-1', sourceTeamId: 1 })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted).toFinishAllListeners()

        mounted.actions.setDestinationTeamId(2)
        await expectLogic(mounted, () => mounted.actions.submitCopy()).toFinishAllListeners()

        expect(api.dashboardTemplates.copyBetweenProjects).toHaveBeenCalledWith(2, 'src-1')
        expect(getAllTemplates).toHaveBeenCalled()
        expect(lemonToast.success).toHaveBeenCalled()
        expect(router.actions.push).toHaveBeenCalledWith(urls.dashboards(), { tab: DashboardsTab.Templates })
    })

    it('submitCopy shows an error toast when the API fails', async () => {
        const copyMock = api.dashboardTemplates.copyBetweenProjects as jest.Mock
        copyMock.mockRejectedValueOnce(new ApiError(undefined, 500, undefined, { detail: 'network' }))

        const mounted = dashboardTemplateCopyLogic({ sourceTemplateId: 'src-1', sourceTeamId: 1 })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted).toFinishAllListeners()
        mounted.actions.setDestinationTeamId(2)

        await expectLogic(mounted, () => mounted.actions.submitCopy()).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalledWith('Submit copy failed: network')
    })

    it('submitCopy without destination shows an error toast', async () => {
        const copyMock = api.dashboardTemplates.copyBetweenProjects as jest.Mock

        const mounted = dashboardTemplateCopyLogic({ sourceTemplateId: 'src-1', sourceTeamId: 1 })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted).toFinishAllListeners()

        await expectLogic(mounted, () => mounted.actions.submitCopy()).toFinishAllListeners()

        expect(copyMock).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalledWith('Select a destination project')
    })

    it('submitCopy surfaces ApiError detail in the toast', async () => {
        const copyMock = api.dashboardTemplates.copyBetweenProjects as jest.Mock
        copyMock.mockRejectedValueOnce(
            new ApiError(undefined, 400, undefined, { detail: 'Org template limit reached' })
        )

        const mounted = dashboardTemplateCopyLogic({ sourceTemplateId: 'src-1', sourceTeamId: 1 })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted).toFinishAllListeners()
        mounted.actions.setDestinationTeamId(2)

        await expectLogic(mounted, () => mounted.actions.submitCopy()).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalledTimes(1)
        expect(lemonToast.error).toHaveBeenCalledWith('Submit copy failed: Org template limit reached')
    })
})
