import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { promiseResolveReject } from 'lib/utils/async'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { CohortType, FilterLogicalOperator } from '~/types'

import { cohortsModel, getReferencedCohortIds, processCohort } from './cohortsModel'

jest.unmock('lib/utils/concurrencyController')

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
                '/api/projects/:team/cohorts/:id/': async ({ request }) => {
                    const data = (await request.json()) as Record<string, any>
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

            await expectLogic(logic).toDispatchActions(['loadAllCohorts', 'loadAllCohortsSuccess'])
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

    describe('individual insights', () => {
        const list = jest.fn(() => MOCK_COHORTS)
        const requestedIds: number[] = []

        beforeEach(async () => {
            await expectLogic(logic).toFinishAllListeners()
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, id: MOCK_DEFAULT_TEAM.id + 1 })
            router.actions.push('/project/997/insights/abc123')
            list.mockClear()
            requestedIds.length = 0
            useMocks({
                get: {
                    '/api/projects/:team/cohorts/': list,
                    '/api/projects/:team/cohorts/:id/': ({ params }) => {
                        if (params.team !== String(MOCK_DEFAULT_TEAM.project_id)) {
                            return [404, { detail: 'Project not found.' }]
                        }
                        const id = Number(params.id)
                        requestedIds.push(id)
                        return { ...MOCK_COHORTS.results[0], id, name: `Cohort ${id}` }
                    },
                },
            })
            logic = cohortsModel()
            logic.mount()
        })

        it('skips the list, resolves only missing IDs, and preserves both cache views', async () => {
            await expectLogic(logic).toFinishAllListeners()
            expect(list).not.toHaveBeenCalled()
            await expectLogic(logic, () => {
                logic.actions.loadCohortsByIds({ ids: [1, 1, 3000, 0, -1] })
                logic.actions.loadCohortsByIds({ ids: [1, 2] })
            }).toFinishAllListeners()
            expect(requestedIds.sort((a, b) => a - b)).toEqual([1, 2, 3000])
            expect(Object.keys(logic.values.cohortsById)).toEqual(['1', '2', '3000'])
            expect(logic.values.cohortsById[3000]?.name).toBe('Cohort 3000')
            expect(logic.values.allCohorts.results).toHaveLength(3)
            await expectLogic(logic, () => logic.actions.loadCohortsByIds({ ids: [1, 3000] })).toFinishAllListeners()
            expect(requestedIds).toHaveLength(3)
            expect(list).not.toHaveBeenCalled()
        })

        it('limits overlapping and nested cohort requests to ten in flight and drains after failures', async () => {
            const firstTen = promiseResolveReject<void>()
            const nextStarted = promiseResolveReject<void>()
            const firstResponse = promiseResolveReject<void>()
            const remainingResponses = promiseResolveReject<void>()
            let active = 0
            let peak = 0
            useMocks({
                get: {
                    '/api/projects/:team/cohorts/:id/': async ({ params }) => {
                        const id = Number(params.id)
                        requestedIds.push(id)
                        peak = Math.max(peak, ++active)
                        if (requestedIds.length === 10) {
                            firstTen.resolve()
                        }
                        if (requestedIds.length === 11) {
                            nextStarted.resolve()
                        }
                        await (id === 1 ? firstResponse.promise : remainingResponses.promise)
                        active--
                        if (id === 2) {
                            return [403, { detail: 'Forbidden.' }]
                        }
                        return {
                            ...MOCK_COHORTS.results[0],
                            id,
                            filters: {
                                properties: {
                                    type: 'AND',
                                    values:
                                        id === 1
                                            ? [{ type: 'cohort', value: Array.from({ length: 15 }, (_, i) => i + 21) }]
                                            : [],
                                },
                            },
                        }
                    },
                },
            })
            logic.actions.loadCohortsByIds({ ids: Array.from({ length: 15 }, (_, i) => i + 1) })
            logic.actions.loadCohortsByIds({ ids: Array.from({ length: 11 }, (_, i) => i + 10) })
            await firstTen.promise
            expect(active).toBe(10)
            expect(requestedIds).toHaveLength(10)
            firstResponse.resolve()
            await nextStarted.promise
            expect(active).toBe(10)
            remainingResponses.resolve()
            await expectLogic(logic).toFinishAllListeners()
            expect(peak).toBe(10)
            expect(requestedIds.sort((a, b) => a - b)).toEqual(Array.from({ length: 35 }, (_, i) => i + 1))
            expect(logic.values.allCohorts.results).toHaveLength(34)
            expect(logic.values.cohortsById[35]).toMatchObject({ id: 35 })
        })

        it.each([
            '/insights/abc123/edit',
            '/project/997/insights/abc123/subscriptions',
            '/project/997/insights/abc123/subscriptions/123',
            '/insights/abc123/alerts',
            '/insights/abc123/alerts/123/',
            '/project/997/insights/abc123/sharing',
            '/insights/new',
        ])('keeps targeted loading when navigating to %s', async (pathname) => {
            await expectLogic(logic, () => router.actions.push(pathname)).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.loadCohortsByIds({ ids: [3000] })).toFinishAllListeners()
            expect(list).not.toHaveBeenCalled()
            expect(requestedIds).toEqual([3000])
            expect(logic.values.cohortsById[3000]?.name).toBe('Cohort 3000')
        })

        it.each([
            '/insights',
            '/insights/quick-start',
            '/project/997/insights/quick-start/',
            '/feature_flags',
            '/cohorts',
            '/dashboard/1',
        ])('loads the full list after navigating to %s', async (pathname) => {
            await expectLogic(logic, () => router.actions.push(pathname)).toFinishAllListeners()
            expect(list).toHaveBeenCalledTimes(1)
            expect(logic.values.cohortsById[2]?.name).toBe('Cohort two')
            await expectLogic(logic, () => router.actions.replace(pathname, { search: 'test' })).toFinishAllListeners()
            expect(list).toHaveBeenCalledTimes(1)
        })

        it('reuses dashboard cohorts and fetches only references outside the loaded list', async () => {
            await expectLogic(logic, () => router.actions.push('/dashboard/1')).toFinishAllListeners()
            expect(list).toHaveBeenCalledTimes(1)
            await expectLogic(logic, () => router.actions.push('/insights/abc123')).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.loadCohortsByIds({ ids: [1, 2, 3000] })).toFinishAllListeners()
            expect(requestedIds).toEqual([3000])
            expect(logic.values.cohortsById[2]?.name).toBe('Cohort two')
            expect(logic.values.cohortsById[3000]?.name).toBe('Cohort 3000')
            expect(list).toHaveBeenCalledTimes(1)
        })

        it('preserves targeted names when a list request finishes after returning to the insight', async () => {
            let releaseList!: () => void
            const listReady = new Promise<void>((resolve) => {
                releaseList = resolve
            })
            useMocks({
                get: {
                    '/api/projects/:team/cohorts/': async () => {
                        await listReady
                        return MOCK_COHORTS
                    },
                },
            })
            await expectLogic(logic, () => logic.actions.loadCohortsByIds({ ids: [3000] })).toFinishAllListeners()
            await expectLogic(logic, () => router.actions.push('/feature_flags')).toDispatchActions(['loadAllCohorts'])
            router.actions.push('/insights/abc123')
            releaseList()
            await expectLogic(logic).toFinishAllListeners()
            expect(Object.keys(logic.values.cohortsById)).toEqual(['1', '2', '3000'])
            expect(logic.values.cohortsById[3000]?.name).toBe('Cohort 3000')
        })

        it('loads nested cohort names without looping on circular references', async () => {
            useMocks({
                get: {
                    '/api/projects/:team/cohorts/:id/': ({ params }) => {
                        const id = Number(params.id)
                        requestedIds.push(id)
                        return {
                            ...MOCK_COHORTS.results[0],
                            id,
                            filters: {
                                properties: { type: 'AND', values: [{ type: 'cohort', value: id === 1 ? 2 : 1 }] },
                            },
                        }
                    },
                },
            })
            await expectLogic(logic, () => logic.actions.loadCohortsByIds({ ids: [1] })).toFinishAllListeners()
            expect(requestedIds).toEqual([1, 2])
            expect(Object.keys(logic.values.cohortsById)).toEqual(['1', '2'])
        })

        it.each([403, 404, 500])('keeps successful names and allows retry after a %s response', async (status) => {
            useMocks({
                get: {
                    '/api/projects/:team/cohorts/2/': [status, { detail: 'Unavailable' }],
                },
            })
            await expectLogic(logic, () => logic.actions.loadCohortsByIds({ ids: [1, 2] })).toFinishAllListeners()
            expect(logic.values.cohortsById[1]?.name).toBe('Cohort 1')
            expect(logic.values.cohortsById[2]).toBeUndefined()
            useMocks({ get: { '/api/projects/:team/cohorts/2/': MOCK_COHORTS.results[1] } })
            await expectLogic(logic, () => logic.actions.loadCohortsByIds({ ids: [2] })).toFinishAllListeners()
            expect(logic.values.cohortsById[2]?.name).toBe('Cohort two')
        })
    })

    describe('referenced cohort IDs', () => {
        it.each([
            [null, []],
            [{ properties: [{ type: 'event', key: 'cohort', value: 42 }] }, []],
            [
                {
                    source: {
                        properties: {
                            type: 'AND',
                            values: [
                                { type: 'cohort', value: '12' },
                                { type: 'cohort', value: [12, 34] },
                            ],
                        },
                        series: [{ properties: [{ type: 'cohort', value: 56 }] }],
                        breakdownFilter: { breakdown_type: 'cohort', breakdown: [34, '78', 'all', 0, -1] },
                    },
                },
                [12, 34, 56, 78],
            ],
            [{ breakdownFilter: { breakdown_type: 'cohort', breakdown: 99 } }, [99]],
            [{ properties: [{ type: 'cohort', value: ['nope', null, true, 1.2] }] }, []],
        ])('extracts references from %j', (query, expected) => {
            expect(getReferencedCohortIds(query)).toEqual(expected)
        })
    })

    describe('cohort operations', () => {
        it('can update a cohort', async () => {
            // Wait for initial load
            await expectLogic(logic).toDispatchActions(['loadAllCohortsSuccess'])

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
                allCohorts: expect.objectContaining({
                    results: expect.arrayContaining([
                        expect.objectContaining({
                            id: 1,
                            name: 'Updated name',
                        }),
                    ]),
                }),
            })
        })

        it('adds a directly-opened cohort to cohortsById when not already loaded', async () => {
            // Mirrors cohortEditLogic.fetchCohort dispatching updateCohort for a cohort that
            // isn't in the loaded list (e.g. opened directly by URL) — its name must reach
            // cohortsById so the breadcrumb / browser tab title shows it instead of "Untitled".
            await expectLogic(logic).toDispatchActions(['loadAllCohortsSuccess'])

            const openedCohort: CohortType = {
                id: 99,
                name: 'Directly opened cohort',
                count: 0,
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
                logic.actions.updateCohort(openedCohort)
            }).toMatchValues({
                cohortsById: expect.objectContaining({
                    99: expect.objectContaining({ id: 99, name: 'Directly opened cohort' }),
                }),
            })
        })

        it('can delete a cohort', async () => {
            // Wait for initial load
            await expectLogic(logic).toDispatchActions(['loadAllCohortsSuccess'])

            jest.spyOn(api.cohorts, 'determineDeleteEndpoint').mockImplementation(() => 'cohorts')

            await expectLogic(logic, () => {
                logic.actions.deleteCohort({ id: 1 })
            })
                .toDispatchActions(['deleteCohort'])
                .toMatchValues({
                    allCohorts: expect.objectContaining({
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

        it('restores a saved person_metadata criterion to editor format (value -> value_property)', () => {
            const cohort = {
                id: 5,
                name: 'First seen cohort',
                count: 0,
                groups: [],
                is_calculating: false,
                is_static: false,
                filters: {
                    properties: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: 'person_metadata',
                                key: 'created_at',
                                operator: 'is_date_after',
                                value: '2024-01-01',
                                negation: false,
                            },
                        ],
                    },
                },
            } as unknown as CohortType

            const result = processCohort(cohort)
            const group = result.filters.properties.values[0]
            // value carries the behavioral row key the editor renders against; the actual
            // filter value moves to value_property. Without this, criteriaToBehavioralFilterType
            // returns the raw date and ROWS[date] is undefined, crashing CohortCriteriaRowBuilder.
            expect((group as any).values[0]).toMatchObject({
                type: 'person_metadata',
                key: 'created_at',
                value: 'have_property',
                value_property: '2024-01-01',
            })
        })

        it('canonicalizes a behavioral value the backend only accepts as an alias', () => {
            const cohort = {
                id: 6,
                name: 'Aliased criterion cohort',
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
                                value: 'performed_event_multiple_times',
                                event_type: 'events',
                                operator: 'gte',
                                operator_value: 2,
                                time_value: 30,
                                time_interval: 'day',
                            },
                        ],
                    },
                },
            } as unknown as CohortType

            const result = processCohort(cohort)
            const group = result.filters.properties.values[0]
            // The alias has no ROWS entry, so leaving it verbatim renders the criterion as
            // unsupported even though the backend resolves and queries it. explicit_datetime only
            // gets converted once the value is canonical, and without it validateGroup rejects the
            // row for a missing time window the criterion already carried.
            expect((group as any).values[0]).toMatchObject({
                value: 'performed_event_multiple',
                explicit_datetime: '-30d',
            })
        })
    })
})
