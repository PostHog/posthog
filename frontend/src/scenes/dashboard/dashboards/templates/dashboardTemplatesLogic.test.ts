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
})
