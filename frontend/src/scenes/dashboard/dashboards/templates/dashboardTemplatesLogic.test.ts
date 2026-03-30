import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import type { DashboardTemplateListParams } from '~/types'

import { dashboardTemplatesLogic } from './dashboardTemplatesLogic'

describe('dashboardTemplatesLogic', () => {
    let logic: ReturnType<typeof dashboardTemplatesLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        jest.spyOn(api.dashboardTemplates, 'list').mockResolvedValue({ results: [] })
        logic = undefined
    })

    afterEach(() => {
        logic?.unmount()
        logic = undefined
        jest.restoreAllMocks()
    })

    it('passes is_featured when listQuery requests featured templates', async () => {
        const listMock = api.dashboardTemplates.list as jest.Mock
        const mounted = dashboardTemplatesLogic({ scope: 'default', listQuery: { is_featured: true } })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted, () => mounted.actions.getAllTemplates()).toFinishAllListeners()

        expect(listMock.mock.calls.some(([params]: [DashboardTemplateListParams]) => params.is_featured === true)).toBe(
            true
        )
    })

    it('does not set is_featured on the default list query', async () => {
        const listMock = api.dashboardTemplates.list as jest.Mock
        const mounted = dashboardTemplatesLogic({ scope: 'default' })
        logic = mounted
        mounted.mount()

        await expectLogic(mounted, () => mounted.actions.getAllTemplates()).toFinishAllListeners()

        expect(listMock).toHaveBeenCalled()
        expect(
            listMock.mock.calls.every(([params]: [DashboardTemplateListParams]) => params.is_featured === undefined)
        ).toBe(true)
    })

    it('omits search for featured list when templateFilter is long', async () => {
        const listMock = api.dashboardTemplates.list as jest.Mock
        const mounted = dashboardTemplatesLogic({ scope: 'default', listQuery: { is_featured: true } })
        logic = mounted
        mounted.mount()
        mounted.actions.setTemplateFilter('needle')

        await expectLogic(mounted, () => mounted.actions.getAllTemplates()).toFinishAllListeners()

        expect(
            listMock.mock.calls.some(
                ([params]: [DashboardTemplateListParams]) => params.is_featured === true && params.search === undefined
            )
        ).toBe(true)
    })

    it('passes search when not featured-only and templateFilter is long', async () => {
        const listMock = api.dashboardTemplates.list as jest.Mock
        const mounted = dashboardTemplatesLogic({ scope: 'default' })
        logic = mounted
        mounted.mount()
        mounted.actions.setTemplateFilter('needle')

        await expectLogic(mounted, () => mounted.actions.getAllTemplates()).toFinishAllListeners()

        expect(listMock.mock.calls.some(([params]: [DashboardTemplateListParams]) => params.search === 'needle')).toBe(
            true
        )
    })
})
