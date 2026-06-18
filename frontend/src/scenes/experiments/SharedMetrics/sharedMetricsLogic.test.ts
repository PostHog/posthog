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

    it('loads the first page with limit and offset 0', async () => {
        jest.spyOn(api, 'get')
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toFinishAllListeners()
        expect(api.get).toHaveBeenCalledWith(expect.stringContaining(`limit=${PAGE_SIZE}`))
        expect(api.get).toHaveBeenCalledWith(expect.stringContaining('offset=0'))
        await expectLogic(logic).toMatchValues({ count: 2 })
    })

    it('setPage reloads with the correct offset', async () => {
        jest.spyOn(api, 'get')
        await expectLogic(logic, () => {
            logic.actions.setPage(2)
        }).toFinishAllListeners()
        expect(api.get).toHaveBeenLastCalledWith(expect.stringContaining(`offset=${PAGE_SIZE}`))
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
        expect(api.get).toHaveBeenLastCalledWith(expect.stringContaining('search=revenue'))
    })

    it('exposes current page and total count', async () => {
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ page: 1, count: 2 })
    })
})
