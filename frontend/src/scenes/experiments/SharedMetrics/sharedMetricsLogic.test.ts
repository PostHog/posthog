import { api } from 'lib/api.mock'

import { expectLogic, partial } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SharedMetric } from './sharedMetricLogic'
import { SHARED_METRICS_PER_PAGE, sharedMetricsLogic } from './sharedMetricsLogic'

const createMockSharedMetric = (id: number, name: string, description?: string): SharedMetric =>
    ({
        id,
        name,
        description: description || `Description for ${name}`,
        query: {
            kind: 'ExperimentTrendsQuery',
            count_query: {
                kind: 'TrendsQuery',
                series: [{ kind: 'EventsNode', event: '$pageview' }],
            },
        },
        created_by: null,
        created_at: '2023-01-01T00:00:00Z',
        updated_at: '2023-01-01T00:00:00Z',
        tags: [],
        user_access_level: 'editor' as const,
    }) as SharedMetric

describe('sharedMetricsLogic', () => {
    let logic: ReturnType<typeof sharedMetricsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/experiment_saved_metrics': {
                    results: [],
                    count: 0,
                },
            },
        })
        initKeaTests()
        jest.spyOn(api, 'get')
        api.get.mockClear()
        logic = sharedMetricsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('loading on mount', () => {
        it('loads shared metrics on mount', async () => {
            // The logic is already mounted in beforeEach, so we just verify it loaded
            await expectLogic(logic).toDispatchActions(['loadSharedMetrics']).toFinishAllListeners()

            expect(api.get).toHaveBeenCalledWith(
                expect.stringMatching(/api\/projects\/@current\/experiment_saved_metrics\?/)
            )
        })
    })

    describe('filters', () => {
        beforeEach(async () => {
            // Wait for initial load to complete
            await expectLogic(logic).toFinishAllListeners()
            api.get.mockClear()
        })

        it('updates search filter and triggers API call with debounce', async () => {
            const mockMetrics = {
                results: [createMockSharedMetric(1, 'Revenue Metric')],
                count: 1,
            }
            api.get.mockResolvedValue(mockMetrics)

            await expectLogic(logic, () => {
                logic.actions.setSharedMetricsFilters({ search: 'revenue' })
            })
                .toMatchValues({
                    filters: partial({ search: 'revenue', page: 1 }),
                })
                .delay(350) // Wait for debounce
                .toFinishAllListeners()

            expect(api.get).toHaveBeenCalledWith(expect.stringContaining('search=revenue'))
        })

        it('resets page to 1 when search filter is applied', async () => {
            logic.actions.setSharedMetricsFilters({ page: 2 })
            expect(logic.values.filters.page).toBe(2)

            await expectLogic(logic, () => {
                logic.actions.setSharedMetricsFilters({ search: 'test', page: 1 })
            }).toMatchValues({
                filters: partial({ search: 'test', page: 1 }),
            })
        })

        it('updates page filter and triggers API call', async () => {
            const mockMetrics = {
                results: [createMockSharedMetric(1, 'Metric 1')],
                count: 35,
            }
            api.get.mockResolvedValue(mockMetrics)

            await expectLogic(logic, () => {
                logic.actions.setSharedMetricsFilters({ page: 2 })
            })
                .toMatchValues({
                    filters: partial({ page: 2 }),
                })
                .delay(350)
                .toFinishAllListeners()

            expect(api.get).toHaveBeenCalledWith(expect.stringContaining('offset=30'))
        })

        it('replaces filters when replace is true', () => {
            logic.actions.setSharedMetricsFilters({ search: 'test', page: 2 })
            expect(logic.values.filters).toEqual({ search: 'test', page: 2 })

            logic.actions.setSharedMetricsFilters({ page: 1 }, true)
            expect(logic.values.filters).toEqual({ page: 1 })
        })
    })

    describe('paramsFromFilters selector', () => {
        it('constructs correct params with search', () => {
            logic.actions.setSharedMetricsFilters({ search: 'revenue', page: 1 })

            expect(logic.values.paramsFromFilters).toEqual({
                search: 'revenue',
                limit: SHARED_METRICS_PER_PAGE,
                offset: 0,
            })
        })

        it('constructs correct params with page', () => {
            logic.actions.setSharedMetricsFilters({ page: 2 })

            expect(logic.values.paramsFromFilters).toEqual({
                limit: SHARED_METRICS_PER_PAGE,
                offset: SHARED_METRICS_PER_PAGE,
            })
        })

        it('constructs correct params with search and page', () => {
            logic.actions.setSharedMetricsFilters({ search: 'conversion', page: 3 })

            expect(logic.values.paramsFromFilters).toEqual({
                search: 'conversion',
                limit: SHARED_METRICS_PER_PAGE,
                offset: 2 * SHARED_METRICS_PER_PAGE,
            })
        })

        it('omits search param when search is undefined', () => {
            logic.actions.setSharedMetricsFilters({ page: 1 })

            expect(logic.values.paramsFromFilters).not.toHaveProperty('search')
        })
    })

    describe('count selector', () => {
        it('returns count from sharedMetrics', () => {
            logic.actions.loadSharedMetricsSuccess({
                results: [],
                count: 42,
            })

            expect(logic.values.count).toBe(42)
        })

        it('returns 0 when sharedMetrics is empty', () => {
            logic.actions.loadSharedMetricsSuccess({
                results: [],
                count: 0,
            })

            expect(logic.values.count).toBe(0)
        })
    })

    describe('pagination selector', () => {
        it('calculates pagination for first page with many results', () => {
            logic.actions.setSharedMetricsFilters({ page: 1 })
            logic.actions.loadSharedMetricsSuccess({
                results: Array.from({ length: SHARED_METRICS_PER_PAGE }, (_, i) =>
                    createMockSharedMetric(i + 1, `Metric ${i + 1}`)
                ),
                count: 100,
            })

            const pagination = logic.values.pagination
            expect(pagination.controlled).toBe(true)
            expect(pagination.pageSize).toBe(SHARED_METRICS_PER_PAGE)
            expect(pagination.currentPage).toBe(1)
            expect(pagination.entryCount).toBe(100)
            expect(pagination.onForward).toBeTruthy()
            expect(pagination.onBackward).toBeUndefined()
        })

        it('calculates pagination for middle page', () => {
            logic.actions.setSharedMetricsFilters({ page: 2 })
            logic.actions.loadSharedMetricsSuccess({
                results: Array.from({ length: SHARED_METRICS_PER_PAGE }, (_, i) =>
                    createMockSharedMetric(i + 31, `Metric ${i + 31}`)
                ),
                count: 100,
            })

            const pagination = logic.values.pagination
            expect(pagination.currentPage).toBe(2)
            expect(pagination.onForward).toBeTruthy()
            expect(pagination.onBackward).toBeTruthy()
        })

        it('calculates pagination for last page', () => {
            logic.actions.setSharedMetricsFilters({ page: 4 })
            logic.actions.loadSharedMetricsSuccess({
                results: Array.from({ length: 10 }, (_, i) => createMockSharedMetric(i + 91, `Metric ${i + 91}`)),
                count: 100,
            })

            const pagination = logic.values.pagination
            expect(pagination.currentPage).toBe(4)
            expect(pagination.onForward).toBeUndefined()
            expect(pagination.onBackward).toBeTruthy()
        })

        it('hides pagination when results fit on one page', () => {
            logic.actions.setSharedMetricsFilters({ page: 1 })
            logic.actions.loadSharedMetricsSuccess({
                results: [createMockSharedMetric(1, 'Metric 1'), createMockSharedMetric(2, 'Metric 2')],
                count: 2,
            })

            const pagination = logic.values.pagination
            expect(pagination.onForward).toBeUndefined()
            expect(pagination.onBackward).toBeUndefined()
        })

        it('pagination forward action updates page', () => {
            logic.actions.setSharedMetricsFilters({ page: 1 })
            logic.actions.loadSharedMetricsSuccess({
                results: [],
                count: 100,
            })

            const pagination = logic.values.pagination
            expect(pagination.onForward).toBeTruthy()

            pagination.onForward?.()
            expect(logic.values.filters.page).toBe(2)
        })

        it('pagination backward action updates page', () => {
            logic.actions.setSharedMetricsFilters({ page: 3 })
            logic.actions.loadSharedMetricsSuccess({
                results: [],
                count: 100,
            })

            const pagination = logic.values.pagination
            expect(pagination.onBackward).toBeTruthy()

            pagination.onBackward?.()
            expect(logic.values.filters.page).toBe(2)
        })

        it('pagination backward does not go below page 1', () => {
            logic.actions.setSharedMetricsFilters({ page: 1 })
            logic.actions.loadSharedMetricsSuccess({
                results: [],
                count: 100,
            })

            const pagination = logic.values.pagination
            expect(pagination.onBackward).toBeUndefined()
        })
    })

    describe('debouncing', () => {
        beforeEach(async () => {
            // Wait for initial load to complete
            await expectLogic(logic).toFinishAllListeners()
            api.get.mockClear()
        })

        it('debounces search filter changes', async () => {
            api.get.mockResolvedValue({ results: [], count: 0 })

            await expectLogic(logic, () => {
                logic.actions.setSharedMetricsFilters({ search: 'r' })
                logic.actions.setSharedMetricsFilters({ search: 're' })
                logic.actions.setSharedMetricsFilters({ search: 'rev' })
                logic.actions.setSharedMetricsFilters({ search: 'revenue' })
            })
                .delay(350)
                .toFinishAllListeners()

            // Should only call API once after debounce (initial load already happened)
            expect(api.get).toHaveBeenCalledTimes(1)
            expect(api.get).toHaveBeenCalledWith(expect.stringContaining('search=revenue'))
        })
    })

    describe('integration', () => {
        beforeEach(async () => {
            // Wait for initial load to complete
            await expectLogic(logic).toFinishAllListeners()
            api.get.mockClear()
        })

        it('loads metrics with search and pagination', async () => {
            const mockMetrics = {
                results: Array.from({ length: SHARED_METRICS_PER_PAGE }, (_, i) =>
                    createMockSharedMetric(i + 1, `Revenue Metric ${i + 1}`)
                ),
                count: 50,
            }
            api.get.mockResolvedValue(mockMetrics)

            await expectLogic(logic, () => {
                logic.actions.setSharedMetricsFilters({ search: 'revenue', page: 1 })
            })
                .delay(350)
                .toFinishAllListeners()
                .toMatchValues({
                    filters: partial({ search: 'revenue', page: 1 }),
                    sharedMetrics: mockMetrics,
                    count: 50,
                })

            expect(api.get).toHaveBeenCalledWith(
                expect.stringMatching(
                    /api\/projects\/@current\/experiment_saved_metrics\?.*search=revenue.*limit=30.*offset=0/
                )
            )
        })

        it('loads second page of results', async () => {
            const mockMetrics = {
                results: Array.from({ length: SHARED_METRICS_PER_PAGE }, (_, i) =>
                    createMockSharedMetric(i + 31, `Metric ${i + 31}`)
                ),
                count: 60,
            }
            api.get.mockResolvedValue(mockMetrics)

            await expectLogic(logic, () => {
                logic.actions.setSharedMetricsFilters({ page: 2 })
            })
                .delay(350)
                .toFinishAllListeners()
                .toMatchValues({
                    filters: partial({ page: 2 }),
                    sharedMetrics: mockMetrics,
                })

            expect(api.get).toHaveBeenCalledWith(
                expect.stringMatching(/api\/projects\/@current\/experiment_saved_metrics\?.*limit=30.*offset=30/)
            )
        })
    })
})
