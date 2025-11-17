import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockCohort } from '~/test/mocks'

import {
    CohortCalculationHistoryRecord,
    CohortCalculationHistoryResponse,
    CohortCalculationHistorySceneLogicProps,
    cohortCalculationHistorySceneLogic,
} from './cohortCalculationHistorySceneLogic'

const mockHistoryRecord: CohortCalculationHistoryRecord = {
    id: 1,
    team: 1,
    cohort: 123,
    filters: { some: 'filter' },
    count: 500,
    started_at: '2023-01-01T10:00:00Z',
    finished_at: '2023-01-01T10:05:00Z',
    queries: [
        {
            query: 'SELECT * FROM events',
            query_id: 'query-1',
            query_ms: 1000,
            memory_mb: 64,
            read_rows: 1000,
            written_rows: 500,
        },
    ],
    error: null,
    total_query_ms: 1000,
    total_memory_mb: 64,
    total_read_rows: 1000,
    total_written_rows: 500,
    main_query: { query: 'main query' },
}

const mockHistoryResponse: CohortCalculationHistoryResponse = {
    results: [mockHistoryRecord],
    count: 1,
    next: null,
    previous: null,
}

describe('cohortCalculationHistorySceneLogic', () => {
    let logic: ReturnType<typeof cohortCalculationHistorySceneLogic.build>

    useMocks({
        get: {
            '/api/cohort/:id/calculation_history/': () => [200, mockHistoryResponse],
            '/api/cohort/:id/': () => [200, mockCohort],
        },
    })

    async function initLogic(props: CohortCalculationHistorySceneLogicProps = { cohortId: 123 }): Promise<void> {
        logic = cohortCalculationHistorySceneLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api, 'get')
        api.get.mockClear()
    })

    describe('initial load', () => {
        it('should load calculation history and cohort on mount with valid cohortId', async () => {
            api.get.mockImplementation((url: string) => {
                if (url.includes('calculation_history')) {
                    return Promise.resolve(mockHistoryResponse)
                }
                return Promise.resolve(mockCohort)
            })

            await initLogic({ cohortId: 123 })

            await expectLogic(logic).toDispatchActions(['loadCalculationHistory', 'loadCohort']).toFinishAllListeners()

            expect(api.get).toHaveBeenCalledTimes(2)
            expect(api.get).toHaveBeenCalledWith('api/cohort/123/calculation_history/?limit=100&offset=0')
            expect(logic.values.calculationHistory).toEqual([mockHistoryRecord])
            expect(logic.values.totalRecords).toBe(1)
            expect(logic.values.cohort).toEqual(mockCohort)
        })

        it('should not load data on mount with invalid cohortId (0)', async () => {
            await initLogic({ cohortId: 0 })

            expect(api.get).toHaveBeenCalledTimes(0)
            expect(logic.values.calculationHistory).toEqual([])
            expect(logic.values.totalRecords).toBe(0)
            expect(logic.values.cohort).toBe(null)
        })

        it('should not load data on mount with invalid cohortId (negative)', async () => {
            await initLogic({ cohortId: -1 })

            expect(api.get).toHaveBeenCalledTimes(0)
            expect(logic.values.calculationHistory).toEqual([])
            expect(logic.values.totalRecords).toBe(0)
            expect(logic.values.cohort).toBe(null)
        })
    })

    describe('pagination state management', () => {
        beforeEach(async () => {
            api.get.mockResolvedValue(mockHistoryResponse)
            await initLogic({ cohortId: 123 })
            api.get.mockClear()
        })

        it('should update page state and reload data when setPage is called', async () => {
            await expectLogic(logic, () => {
                logic.actions.setPage(2)
            })
                .toDispatchActions(['setPage', 'loadCalculationHistory'])
                .toMatchValues({ page: 2 })
                .toFinishAllListeners()

            expect(api.get).toHaveBeenCalledWith('api/cohort/123/calculation_history/?limit=100&offset=100')
        })

        it('should update limit state and reload data when setLimit is called', async () => {
            await expectLogic(logic, () => {
                logic.actions.setLimit(50)
            })
                .toDispatchActions(['setLimit', 'loadCalculationHistory'])
                .toMatchValues({ limit: 50 })
                .toFinishAllListeners()

            expect(api.get).toHaveBeenCalledWith('api/cohort/123/calculation_history/?limit=50&offset=0')
        })

        const paginationTestCases = [
            { description: 'first page with default limit', page: 1, limit: 100, expectedOffset: 0 },
            { description: 'second page with default limit', page: 2, limit: 100, expectedOffset: 100 },
            { description: 'third page with medium limit', page: 3, limit: 50, expectedOffset: 100 },
            { description: 'fifth page with small limit', page: 5, limit: 25, expectedOffset: 100 },
            { description: 'third page with small limit', page: 3, limit: 25, expectedOffset: 50 },
            { description: 'large page with medium limit', page: 10, limit: 50, expectedOffset: 450 },
            { description: 'first page with small limit', page: 1, limit: 10, expectedOffset: 0 },
        ]

        paginationTestCases.forEach(({ description, page, limit, expectedOffset }) => {
            it(`should calculate correct offset for pagination: ${description}`, async () => {
                await expectLogic(logic, () => {
                    logic.actions.setPage(page)
                    logic.actions.setLimit(limit)
                })
                    .toDispatchActions(['setPage', 'loadCalculationHistory', 'setLimit', 'loadCalculationHistory'])
                    .toFinishAllListeners()

                expect(api.get).toHaveBeenLastCalledWith(
                    `api/cohort/123/calculation_history/?limit=${limit}&offset=${expectedOffset}`
                )
            })
        })
    })

    describe('error handling', () => {
        beforeEach(async () => {
            await initLogic({ cohortId: 123 })
        })

        it('should set cohortMissing when loadCalculationHistory receives 404 error', async () => {
            const error404 = new Error('Not found')
            ;(error404 as any).status = 404
            api.get.mockRejectedValueOnce(error404)

            await expectLogic(logic, () => {
                logic.actions.loadCalculationHistory({})
            })
                .toDispatchActions(['loadCalculationHistory', 'setCohortMissing', 'loadCalculationHistoryFailure'])
                .toMatchValues({ cohortMissing: true })
                .toFinishAllListeners()

            expect(logic.values.cohortMissing).toBe(true)
        })

        it('should set cohortMissing when loadCohort fails', async () => {
            const error = new Error('Failed to load cohort')
            api.get.mockRejectedValueOnce(error)

            await expectLogic(logic, () => {
                logic.actions.loadCohort({})
            })
                .toDispatchActions(['loadCohort', 'setCohortMissing'])
                .toMatchValues({ cohortMissing: true })
                .toFinishAllListeners()

            expect(logic.values.cohortMissing).toBe(true)
            expect(logic.values.cohort).toBe(null)
        })

        it('should not set cohortMissing for non-404 errors in loadCalculationHistory', async () => {
            const error500 = new Error('Internal server error')
            ;(error500 as any).status = 500
            api.get.mockRejectedValueOnce(error500)

            await expectLogic(logic, () => {
                logic.actions.loadCalculationHistory({})
            })
                .toDispatchActions(['loadCalculationHistory', 'loadCalculationHistoryFailure'])
                .toMatchValues({ cohortMissing: false })
                .toFinishAllListeners()

            expect(logic.values.cohortMissing).toBe(false)
        })
    })

    describe('selectors', () => {
        beforeEach(async () => {
            await initLogic({ cohortId: 123 })
        })

        it('should return calculation history from calculationHistoryResponse', () => {
            logic.actions.loadCalculationHistorySuccess(mockHistoryResponse)
            expect(logic.values.calculationHistory).toEqual(mockHistoryResponse.results)
        })

        it('should return total records count from calculationHistoryResponse', () => {
            const responseWithCount = { ...mockHistoryResponse, count: 42 }
            logic.actions.loadCalculationHistorySuccess(responseWithCount)
            expect(logic.values.totalRecords).toBe(42)
        })

        it('should return empty array for calculationHistory with empty response', () => {
            const emptyResponse = {
                results: [],
                count: 0,
                next: null,
                previous: null,
            }
            logic.actions.loadCalculationHistorySuccess(emptyResponse)
            expect(logic.values.calculationHistory).toEqual([])
        })

        it('should return 0 for totalRecords with empty response', () => {
            const emptyResponse = {
                results: [],
                count: 0,
                next: null,
                previous: null,
            }
            logic.actions.loadCalculationHistorySuccess(emptyResponse)
            expect(logic.values.totalRecords).toBe(0)
        })
    })

    describe('API calls with correct parameters', () => {
        it('should make API call with correct URL format for calculation history', async () => {
            api.get.mockResolvedValue(mockHistoryResponse)
            await initLogic({ cohortId: 456 })

            expect(api.get).toHaveBeenCalledWith('api/cohort/456/calculation_history/?limit=100&offset=0')
        })

        it('should handle pagination parameters correctly in API calls', async () => {
            api.get.mockResolvedValue(mockHistoryResponse)
            await initLogic({ cohortId: 789 })
            api.get.mockClear()

            // Set custom page and limit
            await expectLogic(logic, () => {
                logic.actions.setPage(3)
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setLimit(25)
            }).toFinishAllListeners()

            expect(api.get).toHaveBeenLastCalledWith('api/cohort/789/calculation_history/?limit=25&offset=50')
        })
    })

    describe('feature flag access control', () => {
        it('should return true for hasCalculationHistoryAccess when feature flag is enabled', async () => {
            await initLogic({ cohortId: 123 })

            // Mock feature flags with COHORT_CALCULATION_HISTORY enabled
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.COHORT_CALCULATION_HISTORY]: true })

            expect(logic.values.hasCalculationHistoryAccess).toBe(true)
        })

        it('should return false for hasCalculationHistoryAccess when feature flag is disabled', async () => {
            await initLogic({ cohortId: 123 })

            // Mock feature flags with COHORT_CALCULATION_HISTORY disabled
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.COHORT_CALCULATION_HISTORY]: false })

            expect(logic.values.hasCalculationHistoryAccess).toBe(false)
        })

        it('should return false for hasCalculationHistoryAccess when feature flag is undefined', async () => {
            await initLogic({ cohortId: 123 })

            // Mock feature flags without COHORT_CALCULATION_HISTORY
            featureFlagLogic.actions.setFeatureFlags([], {})

            expect(logic.values.hasCalculationHistoryAccess).toBe(false)
        })
    })
})
