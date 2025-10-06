import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { cohortsSceneLogic } from './cohortsSceneLogic'

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
const blankScene = (): any => ({ scene: { component: () => null, logic: null } })
const scenes: any = { [Scene.Dashboards]: blankScene }

describe('cohortsSceneLogic', () => {
    let logic: ReturnType<typeof cohortsSceneLogic.build>

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
        sceneLogic({ scenes }).mount()
        sceneLogic.actions.setTabs([
            { id: '1', title: '...', pathname: '/', search: '', hash: '', active: true, iconType: 'blank' },
        ])
        logic = cohortsSceneLogic({ tabId: '1' })
        logic.mount()
    })

    describe('cohortsSceneLogic', () => {
        describe('core assumptions', () => {
            it('sets polling timeout for calculating cohorts when on cohorts page', async () => {
                // Set the current location to the cohorts page
                router.actions.push(urls.cohorts())

                await expectLogic(logic).toDispatchActions(['loadCohorts', 'loadCohortsSuccess'])
                expect(logic.values.pollTimeout).not.toBeNull()
            })
        })

        describe('cohort filters', () => {
            it('can set and update filters', async () => {
                // Navigate to cohorts page first
                router.actions.push(urls.cohorts())

                // Wait for initial load
                await expectLogic(logic).toDispatchActions(['loadCohortsSuccess'])

                // Test search filter
                await expectLogic(logic, () => {
                    logic.actions.setCohortFilters({ search: 'test' })
                })
                    .toDispatchActions(['setCohortFilters', 'loadCohorts', 'loadCohortsSuccess'])
                    .toMatchValues({
                        cohortFilters: expect.objectContaining({ search: 'test' }),
                    })

                // Test pagination
                await expectLogic(logic, () => {
                    logic.actions.setCohortFilters({ page: 2 })
                })
                    .toDispatchActions(['setCohortFilters', 'loadCohorts', 'loadCohortsSuccess'])
                    .toMatchValues({
                        cohortFilters: expect.objectContaining({ page: 2 }),
                    })

                // Test type filter
                await expectLogic(logic, () => {
                    logic.actions.setCohortFilters({ type: 'static' })
                })
                    .toDispatchActions(['setCohortFilters', 'loadCohorts', 'loadCohortsSuccess'])
                    .toMatchValues({
                        cohortFilters: expect.objectContaining({ type: 'static' }),
                    })

                // Test created_by_id filter
                await expectLogic(logic, () => {
                    logic.actions.setCohortFilters({ created_by_id: 123 })
                })
                    .toDispatchActions(['setCohortFilters', 'loadCohorts', 'loadCohortsSuccess'])
                    .toMatchValues({
                        cohortFilters: expect.objectContaining({ created_by_id: 123 }),
                    })
            })
        })

        describe('cohort operations', () => {
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
            it('correctly calculates pagination values', async () => {
                router.actions.push(urls.cohorts())
                // Wait for the initial load
                await expectLogic(logic).toDispatchActions(['loadCohortsSuccess'])

                await expectLogic(logic).toMatchValues({
                    pagination: expect.objectContaining({
                        currentPage: 1,
                        pageSize: 100,
                        entryCount: 2,
                    }),
                })
            })

            it('calculates shouldShowEmptyState correctly', async () => {
                router.actions.push(urls.cohorts())

                // With cohorts loaded, should not show empty state
                await expectLogic(logic).toDispatchActions(['loadCohortsSuccess'])
                expect(logic.values.shouldShowEmptyState).toBe(false)

                // With no cohorts and default filters, should show empty state
                logic.actions.loadCohortsSuccess({ count: 0, results: [] })
                expect(logic.values.shouldShowEmptyState).toBe(true)

                // With no cohorts but with search filter, should not show empty state
                logic.actions.setCohortFilters({ search: 'test' })
                expect(logic.values.shouldShowEmptyState).toBe(false)
            })
        })
    })
})
