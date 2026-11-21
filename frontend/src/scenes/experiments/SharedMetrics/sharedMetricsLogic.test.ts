import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { PAGE_SIZE, sharedMetricsLogic } from './sharedMetricsLogic'

describe('sharedMetricsLogic', () => {
    let logic: ReturnType<typeof sharedMetricsLogic.build>

    const makeMetrics = (count: number, search: string, offset: number): any => ({
        count,
        results: [
            { id: 1, name: `${search || 'metric'} a` },
            { id: 2, name: `${search || 'metric'} b` },
        ].slice(offset > 0 ? 1 : 0),
    })

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/experiment_saved_metrics': ({ request }) => {
                    const url = new URL(request.url)
                    return [
                        200,
                        makeMetrics(
                            2,
                            url.searchParams.get('search') ?? '',
                            parseInt(url.searchParams.get('offset') ?? '0')
                        ),
                    ]
                },
            },
        })
        initKeaTests()
        logic = sharedMetricsLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    const lastRequestParams = (): URLSearchParams =>
        new URL((api.get as jest.Mock).mock.lastCall[0], 'http://localhost').searchParams

    it('loads the first page with limit and offset 0', async () => {
        jest.spyOn(api, 'get')
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toFinishAllListeners()
        expect(lastRequestParams().get('limit')).toEqual(String(PAGE_SIZE))
        expect(lastRequestParams().get('offset')).toEqual('0')
        await expectLogic(logic).toMatchValues({ count: 2 })
    })

    it('setPage reloads with the correct offset', async () => {
        jest.spyOn(api, 'get')
        await expectLogic(logic, () => {
            logic.actions.setPage(2)
        }).toFinishAllListeners()
        expect(lastRequestParams().get('offset')).toEqual(String(PAGE_SIZE))
        await expectLogic(logic).toMatchValues({ page: 2 })
    })

    it('setSearchTerm resets page to 1 and reloads with search', async () => {
        logic.actions.setPage(3)
        await expectLogic(logic).toMatchValues({ page: 3 })

        jest.spyOn(api, 'get')
        await expectLogic(logic, () => {
            logic.actions.setSearchTerm('revenue')
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ page: 1, searchTerm: 'revenue' })
        expect(lastRequestParams().get('search')).toEqual('revenue')
    })

    it('setFilters resets page to 1 and reloads with JSON-encoded filters', async () => {
        logic.actions.setPage(3)
        await expectLogic(logic).toMatchValues({ page: 3 })

        jest.spyOn(api, 'get')
        await expectLogic(logic, () => {
            logic.actions.setFilters({ created_by_id: [7, 9], tags: ['growth'], metric_type: 'funnel' })
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ page: 1, hasActiveFilters: true })
        const params = lastRequestParams()
        expect(params.get('created_by_id')).toEqual('[7,9]')
        expect(params.get('tags')).toEqual('["growth"]')
        expect(params.get('metric_type')).toEqual('funnel')
        expect(params.get('offset')).toEqual('0')
    })

    it('exposes current page and total count', async () => {
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ page: 1, count: 2 })
    })
})
