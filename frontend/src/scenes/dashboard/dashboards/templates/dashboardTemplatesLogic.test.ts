import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import type { DashboardTemplateListParams, DashboardTemplateType } from '~/types'

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
