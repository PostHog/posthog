import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { METRIC_CONTEXTS } from './experimentMetricModalLogic'
import { MODAL_PAGE_SIZE, sharedMetricModalLogic } from './sharedMetricModalLogic'

const metric = (id: number, kind: NodeKind = NodeKind.ExperimentMetric): any => ({
    id,
    name: `metric ${id}`,
    query: { kind },
})

describe('sharedMetricModalLogic', () => {
    let logic: ReturnType<typeof sharedMetricModalLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/experiment_saved_metrics': ({ request }) => {
                    const url = new URL(request.url)
                    const offset = parseInt(url.searchParams.get('offset') ?? '0')
                    const search = url.searchParams.get('search') ?? ''
                    if (search === 'nomatch') {
                        return [200, { count: 0, next: null, previous: null, results: [] }]
                    }
                    if (offset === 0) {
                        return [
                            200,
                            {
                                count: 3,
                                next: `http://localhost/api/projects/997/experiment_saved_metrics?limit=${MODAL_PAGE_SIZE}&offset=${MODAL_PAGE_SIZE}&search=${search}`,
                                previous: null,
                                results: [metric(1), metric(2, NodeKind.ExperimentTrendsQuery)],
                            },
                        ]
                    }
                    return [200, { count: 3, next: null, previous: null, results: [metric(3)] }]
                },
            },
        })
        initKeaTests()
        logic = sharedMetricModalLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('openSharedMetricModal resets search and loads page 1 with limit 20 offset 0', async () => {
        jest.spyOn(api, 'get')
        await expectLogic(logic, () => {
            logic.actions.setSearchTerm('stale')
            logic.actions.openSharedMetricModal(METRIC_CONTEXTS.primary)
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ searchTerm: '' })
        expect(api.get).toHaveBeenLastCalledWith(expect.stringContaining(`limit=${MODAL_PAGE_SIZE}`))
        expect(api.get).toHaveBeenLastCalledWith(expect.stringContaining('offset=0'))
    })

    it('compatibleSharedMetrics filters out non-ExperimentMetric kinds', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({
            compatibleSharedMetrics: [expect.objectContaining({ id: 1 })],
            canLoadMore: true,
        })
    })

    it('loadNextSharedMetrics appends the next page', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.loadNextSharedMetrics(null)
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({
            compatibleSharedMetrics: [expect.objectContaining({ id: 1 }), expect.objectContaining({ id: 3 })],
            canLoadMore: false,
        })
    })

    it('setSearchTerm triggers a debounced reload with search and replaces results', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toFinishAllListeners()

        jest.spyOn(api, 'get')
        await expectLogic(logic, () => {
            logic.actions.setSearchTerm('revenue')
        }).toFinishAllListeners()
        expect(api.get).toHaveBeenLastCalledWith(expect.stringContaining('search=revenue'))
        await expectLogic(logic).toMatchValues({
            compatibleSharedMetrics: [expect.objectContaining({ id: 1 })],
        })
    })

    it('tracks hasAnyCompatibleSharedMetrics from the unfiltered baseline, not the current search', async () => {
        // initial unfiltered load establishes that compatible metrics exist
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ hasAnyCompatibleSharedMetrics: true })

        // a search that returns zero must NOT flip the baseline to false
        await expectLogic(logic, () => {
            logic.actions.setSearchTerm('nomatch')
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({
            compatibleSharedMetrics: [],
            hasAnyCompatibleSharedMetrics: true,
        })
    })

    it('hasAnyCompatibleSharedMetrics is false when the unfiltered load has no compatible metrics', async () => {
        // mount with a fresh mock where the baseline genuinely has none
        useMocks({
            get: {
                '/api/projects/:team_id/experiment_saved_metrics': () => [
                    200,
                    { count: 0, next: null, previous: null, results: [] },
                ],
            },
        })
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ hasAnyCompatibleSharedMetrics: false })
    })
})
