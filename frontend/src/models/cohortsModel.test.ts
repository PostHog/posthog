import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { CohortType, FilterLogicalOperator } from '~/types'

import { cohortsModel, processCohort } from './cohortsModel'

const MOCK_COHORTS = {
    count: 2,
    results: [
        {
            id: 1,
            name: 'Cohort one',
            count: 1,
            groups: [],
            filters: {
                properties: {
                    type: 'AND',
                    values: [],
                },
            },
            is_calculating: false,
            is_static: false,
            created_at: '2023-08-01T00:00:00Z',
        },
        {
            id: 2,
            name: 'Cohort two',
            count: 2,
            groups: [],
            filters: {
                properties: {
                    type: 'AND',
                    values: [],
                },
            },
            is_calculating: true,
            is_static: false,
            created_at: '2023-08-02T00:00:00Z',
        },
    ],
}

describe('cohortsModel', () => {
    let logic: ReturnType<typeof cohortsModel.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/cohorts/': MOCK_COHORTS,
            },
            delete: {
                '/api/projects/:team/cohorts/:id/': { success: true },
            },
            patch: {
                '/api/projects/:team/cohorts/:id/': (req) => {
                    const data = req.body as Record<string, any>
                    return { ...MOCK_COHORTS.results[0], ...data }
                },
            },
        })
        initKeaTests()
        logic = cohortsModel()
        logic.mount()
    })

    describe('core assumptions', () => {
        it('loads cohorts on mount', async () => {
            await expectLogic(logic).toDispatchActions(['loadAllCohorts', 'loadAllCohortsSuccess'])
            expect(logic.values.allCohorts.results).toHaveLength(2)
        })

        it('sets polling timeout for calculating cohorts when on cohorts page', async () => {
            // Set the current location to the cohorts page
            router.actions.push(urls.cohorts())

            await expectLogic(logic).toDispatchActions(['loadCohorts', 'loadCohortsSuccess'])
            expect(logic.values.pollTimeout).not.toBeNull()
        })

        it('does not set polling timeout when not on cohorts page', async () => {
            // Set the current location to a different page
            router.actions.push(urls.dashboards())

            // Mock API to return cohorts with no calculating ones
            useMocks({
                get: {
                    '/api/projects/:team/cohorts/': {
                        ...MOCK_COHORTS,
                        results: MOCK_COHORTS.results.map((c) => ({ ...c, is_calculating: false })),
                    },
                },
            })

            await expectLogic(logic).toDispatchActions(['loadAllCohorts', 'loadAllCohortsSuccess'])
            expect(logic.values.pollTimeout).toBeNull()
        })
    })

    describe('cohort operations', () => {
        it('can update a cohort', async () => {
            // Wait for initial load
            await expectLogic(logic).toDispatchActions(['loadCohortsSuccess'])

            const updatedCohort: CohortType = {
                id: 1,
                name: 'Updated name',
                count: 1,
                groups: [],
                filters: {
                    properties: {
                        type: FilterLogicalOperator.And,
                        values: [],
                    },
                },
                is_calculating: false,
                is_static: false,
            }

            await expectLogic(logic, () => {
                logic.actions.updateCohort(updatedCohort)
            }).toMatchValues({
                cohorts: expect.objectContaining({
                    results: expect.arrayContaining([
                        expect.objectContaining({
                            id: 1,
                            name: 'Updated name',
                        }),
                    ]),
                }),
            })
        })

        it('can delete a cohort', async () => {
            // Wait for initial load
            await expectLogic(logic).toDispatchActions(['loadCohortsSuccess'])

            jest.spyOn(api.cohorts, 'determineDeleteEndpoint').mockImplementation(() => 'cohorts')

            await expectLogic(logic, () => {
                logic.actions.deleteCohort({ id: 1 })
            })
                .toDispatchActions(['deleteCohort'])
                .toMatchValues({
                    cohorts: expect.objectContaining({
                        results: expect.not.arrayContaining([
                            expect.objectContaining({
                                id: 1,
                            }),
                        ]),
                    }),
                })
        })
    })

    describe('selectors', () => {
        it('correctly maps cohorts by id', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadAllCohortsSuccess'])
                .toMatchValues({
                    cohortsById: expect.objectContaining({
                        1: expect.objectContaining({ id: 1, name: 'Cohort one' }),
                        2: expect.objectContaining({ id: 2, name: 'Cohort two' }),
                    }),
                })
        })
    })

    describe('processCohort', () => {
        it.each([
            {
                name: 'wraps flat criteria into nested group format',
                cohort: {
                    id: 3,
                    name: 'Flat format cohort',
                    count: 0,
                    groups: [],
                    is_calculating: false,
                    is_static: false,
                    filters: {
                        properties: {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: 'behavioral',
                                    key: 'purchase',
                                    value: 'performed_event',
                                    event_type: 'events',
                                    operator: 'gte',
                                    operator_value: 2,
                                    time_value: 30,
                                    time_interval: 'day',
                                    negation: false,
                                },
                            ],
                        },
                    },
                } as CohortType,
                expectedType: FilterLogicalOperator.And,
                expectedCriteriaKey: 'purchase',
            },
            {
                name: 'leaves already nested criteria unchanged',
                cohort: {
                    id: 4,
                    name: 'Nested format cohort',
                    count: 0,
                    groups: [],
                    is_calculating: false,
                    is_static: false,
                    filters: {
                        properties: {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: FilterLogicalOperator.And,
                                    values: [
                                        {
                                            type: 'behavioral',
                                            key: 'purchase',
                                            value: 'performed_event',
                                            event_type: 'events',
                                            explicit_datetime: '-30d',
                                        },
                                    ],
                                },
                            ],
                        },
                    },
                } as CohortType,
                expectedType: FilterLogicalOperator.And,
                expectedCriteriaKey: 'purchase',
            },
        ])('$name', ({ cohort, expectedType, expectedCriteriaKey }) => {
            const result = processCohort(cohort)
            const group = result.filters.properties.values[0]
            expect(group).toHaveProperty('type', expectedType)
            expect(group).toHaveProperty('values')
            expect((group as any).values).toHaveLength(1)
            expect((group as any).values[0]).toMatchObject({
                type: 'behavioral',
                key: expectedCriteriaKey,
            })
        })
    })
})
