import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DEFAULT_CLUSTERING_PARAMS, clustersAdminLogic } from './clustersAdminLogic'

describe('clustersAdminLogic', () => {
    let logic: ReturnType<typeof clustersAdminLogic.build>

    beforeEach(() => {
        initKeaTests()
        // clusteringConfigLogic (connected) loads this on mount; the unhandled-request
        // floor lacks event_filters, which would corrupt its localEventFilters reducer.
        useMocks({
            get: {
                '/api/environments/:team_id/llm_analytics/clustering_config/': {
                    event_filters: [],
                    created_at: '2026-01-01T00:00:00Z',
                    updated_at: '2026-01-01T00:00:00Z',
                },
            },
        })
        logic = clustersAdminLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('reducers', () => {
        describe('isModalOpen', () => {
            it('defaults to closed', () => {
                expect(logic.values.isModalOpen).toBe(false)
            })

            it('opens modal via openModal action', async () => {
                await expectLogic(logic, () => {
                    logic.actions.openModal()
                }).toMatchValues({
                    isModalOpen: true,
                })
            })

            it('closes modal via closeModal action', async () => {
                logic.actions.openModal()

                await expectLogic(logic, () => {
                    logic.actions.closeModal()
                }).toMatchValues({
                    isModalOpen: false,
                })
            })

            it('closes modal on successful clustering run', async () => {
                logic.actions.openModal()

                await expectLogic(logic, () => {
                    logic.actions.triggerClusteringRunSuccess({
                        workflow_id: 'test-workflow',
                        status: 'started',
                        parameters: { ...DEFAULT_CLUSTERING_PARAMS, team_id: 1 },
                    })
                }).toMatchValues({
                    isModalOpen: false,
                })
            })
        })

        describe('params', () => {
            it('defaults to DEFAULT_CLUSTERING_PARAMS', () => {
                expect(logic.values.params).toEqual(DEFAULT_CLUSTERING_PARAMS)
            })

            it('updates params via setParams action', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setParams({ lookback_days: 14 })
                }).toMatchValues({
                    params: { ...DEFAULT_CLUSTERING_PARAMS, lookback_days: 14 },
                })
            })

            it('merges multiple param updates', async () => {
                logic.actions.setParams({ lookback_days: 14 })

                await expectLogic(logic, () => {
                    logic.actions.setParams({ max_samples: 5000 })
                }).toMatchValues({
                    params: {
                        ...DEFAULT_CLUSTERING_PARAMS,
                        lookback_days: 14,
                        max_samples: 5000,
                    },
                })
            })

            it('updates clustering method params', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setParams({
                        clustering_method: 'kmeans',
                        kmeans_min_k: 5,
                        kmeans_max_k: 20,
                    })
                }).toMatchValues({
                    params: {
                        ...DEFAULT_CLUSTERING_PARAMS,
                        clustering_method: 'kmeans',
                        kmeans_min_k: 5,
                        kmeans_max_k: 20,
                    },
                })
            })

            it('resets params via resetParams action', async () => {
                logic.actions.setParams({
                    lookback_days: 30,
                    max_samples: 10000,
                    clustering_method: 'kmeans',
                })

                await expectLogic(logic, () => {
                    logic.actions.resetParams()
                }).toMatchValues({
                    params: DEFAULT_CLUSTERING_PARAMS,
                })
            })
        })
    })

    describe('selectors', () => {
        describe('isRunning', () => {
            it('defaults to false when not loading', () => {
                expect(logic.values.isRunning).toBe(false)
            })
        })
    })

    describe('loaders', () => {
        describe('clusteringRun', () => {
            it('defaults to null', () => {
                expect(logic.values.clusteringRun).toBeNull()
            })
        })
    })
})
