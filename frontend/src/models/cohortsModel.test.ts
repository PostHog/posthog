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
        it('correctly processes cohort with flat criteria array', () => {
            const cohortWithFlatCriteria: CohortType = {
                id: 1,
                name: 'Test cohort',
                count: 0,
                groups: [],
                filters: {
                    properties: {
                        type: FilterLogicalOperator.Or,
                        values: [
                            {
                                type: 'person',
                                key: 'email',
                                operator: 'icontains',
                                value: 'domain1',
                            },
                            {
                                type: 'person',
                                key: 'email',
                                operator: 'exact',
                                value: 'user@example.com',
                            },
                        ],
                    },
                },
                is_calculating: false,
                is_static: false,
            }

            const processed = processCohort(cohortWithFlatCriteria)

            expect(processed.filters.properties.values).toHaveLength(1)
            expect(processed.filters.properties.values[0]).toMatchObject({
                type: FilterLogicalOperator.Or,
                values: expect.arrayContaining([
                    expect.objectContaining({
                        type: 'person',
                        key: 'email',
                        operator: 'icontains',
                        value: 'domain1',
                        value_property: 'domain1',
                    }),
                    expect.objectContaining({
                        type: 'person',
                        key: 'email',
                        operator: 'exact',
                        value: 'user@example.com',
                        value_property: 'user@example.com',
                    }),
                ]),
            })
            expect(processed.filters.properties.values[0].values).toHaveLength(2)
        })

        it('correctly processes cohort with existing group structure', () => {
            const cohortWithGroups: CohortType = {
                id: 1,
                name: 'Test cohort',
                count: 0,
                groups: [],
                filters: {
                    properties: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                id: 'group1',
                                type: FilterLogicalOperator.Or,
                                values: [
                                    {
                                        type: 'person',
                                        key: 'email',
                                        operator: 'icontains',
                                        value: 'domain1',
                                    },
                                ],
                            },
                        ],
                    },
                },
                is_calculating: false,
                is_static: false,
            }

            const processed = processCohort(cohortWithGroups)

            // Should preserve existing group structure
            expect(processed.filters.properties.values).toHaveLength(1)
            expect(processed.filters.properties.values[0]).toMatchObject({
                id: 'group1',
                type: FilterLogicalOperator.Or,
                values: [
                    expect.objectContaining({
                        type: 'person',
                        key: 'email',
                        operator: 'icontains',
                        value: 'domain1',
                        value_property: 'domain1',
                    }),
                ],
            })
        })
    })
})
