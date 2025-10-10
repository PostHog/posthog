import { api } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { NEW_FLAG } from 'scenes/feature-flags/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { Experiment, ExperimentsTabs, FeatureFlagType, ProgressStatus } from '~/types'

import { experimentsLogic, getExperimentStatus, getExperimentStatusColor } from './experimentsLogic'

const createMockExperiment = (overrides: any = {}): Experiment =>
    ({
        id: 1,
        name: 'Test Experiment',
        feature_flag_key: 'test-experiment',
        start_date: '2023-01-01T00:00:00Z',
        end_date: '2023-01-07T00:00:00Z',
        archived: false,
        ...overrides,
    }) as Experiment

const mockExperiment = createMockExperiment()

const mockRunningExperiment = createMockExperiment({
    id: 2,
    name: 'Running Experiment',
    start_date: '2023-01-01T00:00:00Z',
    end_date: null,
})

const mockDraftExperiment = createMockExperiment({
    id: 3,
    name: 'Draft Experiment',
    start_date: null,
    end_date: null,
})

const mkFlag = (id: number, key: string): FeatureFlagType => ({ ...NEW_FLAG, id, key })

describe('experimentsLogic', () => {
    let logic: ReturnType<typeof experimentsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api, 'get')
        jest.spyOn(api, 'update')
        jest.spyOn(api, 'create')
        api.get.mockClear()
        api.update.mockClear()
        api.create.mockClear()
        logic = experimentsLogic()
        logic.mount()
    })

    describe('feature flag modal filters', () => {
        it('loads feature flags on mount', async () => {
            await expectLogic(logic).toFinishAllListeners()

            expect(api.get).toHaveBeenCalledWith(expect.stringMatching(/api\/projects\/\d+\/feature_flags\/\?/))
        })

        it('updates filters and triggers new API call', async () => {
            api.get.mockClear()

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagModalFilters({ search: 'test', page: 1 })
            })
                .toMatchValues({
                    featureFlagModalFilters: expect.objectContaining({
                        search: 'test',
                        page: 1,
                    }),
                })
                .delay(350) // Wait for debounce
                .toFinishAllListeners()

            expect(api.get).toHaveBeenCalledWith(expect.stringContaining('search=test'))
        })

        it('resets filters to defaults', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagModalFilters({ search: 'test' })
                logic.actions.resetFeatureFlagModalFilters()
            }).toMatchValues({
                featureFlagModalFilters: {
                    active: undefined,
                    created_by_id: undefined,
                    search: undefined,
                    order: undefined,
                    page: 1,
                    evaluation_runtime: undefined,
                },
            })
        })

        it('resets filters and reloads feature flags', async () => {
            api.get.mockClear()

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagModalFilters({ search: 'test' })
            })
                .delay(350) // Wait for debounce
                .toFinishAllListeners()

            api.get.mockClear()

            await expectLogic(logic, () => {
                logic.actions.resetFeatureFlagModalFilters()
            })
                .toMatchValues({
                    featureFlagModalFilters: {
                        active: undefined,
                        created_by_id: undefined,
                        search: undefined,
                        order: undefined,
                        page: 1,
                        evaluation_runtime: undefined,
                    },
                })
                .toFinishAllListeners()

            expect(api.get).toHaveBeenCalledWith(
                expect.stringMatching(/api\/projects\/\d+\/experiments\/eligible_feature_flags\/\?/)
            )
        })

        it('hides pagination when insufficient results', () => {
            // Set up a scenario with few results (less than FLAGS_PER_PAGE)
            logic.actions.loadFeatureFlagModalFeatureFlagsSuccess({
                results: [mkFlag(1, 'flag1'), mkFlag(2, 'flag2')],
                count: 2,
            })

            expect(logic.values.featureFlagModalPagination.onForward).toBe(undefined)
            expect(logic.values.featureFlagModalPagination.onBackward).toBe(undefined)
        })

        it('shows pagination when results exceed page size', () => {
            // Set up a scenario with many results (more than FLAGS_PER_PAGE = 100)
            const manyResults = Array.from({ length: 50 }, (_, i) => mkFlag(i, `flag${i}`))
            logic.actions.loadFeatureFlagModalFeatureFlagsSuccess({
                results: manyResults,
                count: 150, // Total count is more than one page
            })

            expect(logic.values.featureFlagModalPagination.onForward).toBeTruthy()
            expect(logic.values.featureFlagModalPagination.onBackward).toBe(undefined) // First page, no backward
        })

        it('shows backward pagination on non-first page', () => {
            logic.actions.setFeatureFlagModalFilters({ page: 2 })

            const manyResults = Array.from({ length: 50 }, (_, i) => mkFlag(i, `flag${i}`))
            logic.actions.loadFeatureFlagModalFeatureFlagsSuccess({
                results: manyResults,
                count: 250, // Total count spans multiple pages
            })

            expect(logic.values.featureFlagModalPagination.onForward).toBeTruthy()
            expect(logic.values.featureFlagModalPagination.onBackward).toBeTruthy()
        })

        it('hides pagination when on page 2+ but filtered results are insufficient', () => {
            // User navigates to page 2
            logic.actions.setFeatureFlagModalFilters({ page: 2 })

            // Then applies filter that results in very few results (less than FLAGS_PER_PAGE)
            logic.actions.loadFeatureFlagModalFeatureFlagsSuccess({
                results: [mkFlag(1, 'filtered-flag1'), mkFlag(2, 'filtered-flag2')],
                count: 2, // Only 2 total results, not enough for pagination
            })

            // Pagination should be hidden since total results don't warrant it
            expect(logic.values.featureFlagModalPagination.onForward).toBe(undefined)
            expect(logic.values.featureFlagModalPagination.onBackward).toBe(undefined)
        })

        it('resets page to 1 when search filter is applied from page 2', () => {
            // User navigates to page 2
            logic.actions.setFeatureFlagModalFilters({ page: 2 })
            expect(logic.values.featureFlagModalFilters.page).toBe(2)

            // User applies a search filter (simulating what FeatureFlagFiltersSection does)
            logic.actions.setFeatureFlagModalFilters({ search: 'test', page: 1 })

            // Should reset to page 1
            expect(logic.values.featureFlagModalFilters.page).toBe(1)
            expect(logic.values.featureFlagModalFilters.search).toBe('test')
        })

        it('removes ff_page URL parameter when page is reset to 1 via filters', () => {
            // Mock router to capture URL changes
            const mockPush = jest.fn()
            router.actions.push = mockPush

            // User navigates to page 2 first
            logic.actions.setFeatureFlagModalFilters({ page: 2 })

            // This should add ff_page=2 to URL
            expect(mockPush).toHaveBeenLastCalledWith(expect.stringContaining('ff_page=2'))

            mockPush.mockClear()

            // User applies a search filter which includes page: 1
            logic.actions.setFeatureFlagModalFilters({ search: 'test', page: 1 })

            // This should remove ff_page from URL (since page is 1)
            expect(mockPush).toHaveBeenLastCalledWith(expect.not.stringContaining('ff_page'))
        })

        it('constructs API params correctly', async () => {
            logic.actions.setFeatureFlagModalFilters({
                search: 'test',
                active: 'true',
                page: 2,
            })

            await expectLogic(logic).toMatchValues({
                featureFlagModalParamsFromFilters: {
                    search: 'test',
                    active: 'true',
                    page: 2,
                    limit: 100,
                    offset: 100,
                },
            })
        })
    })

    describe('experiments filtering and loading', () => {
        beforeEach(() => {
            api.get.mockClear()
        })

        it('loads experiments on mount', async () => {
            api.get.mockClear()

            await expectLogic(logic, () => {
                logic.actions.loadExperiments()
            }).toFinishAllListeners()

            expect(api.get).toHaveBeenCalledWith(expect.stringMatching(/api\/projects\/\d+\/experiments\?/))
        })

        it('updates filters and triggers API call with debounce', async () => {
            api.get.mockClear()

            await expectLogic(logic, () => {
                logic.actions.setExperimentsFilters({ search: 'test experiment' })
            })
                .delay(350)
                .toFinishAllListeners()

            expect(api.get).toHaveBeenCalledWith(expect.stringContaining('search=test%20experiment'))
        })

        it('handles tab switching', async () => {
            api.get.mockClear()

            await expectLogic(logic, () => {
                logic.actions.setExperimentsTab(ExperimentsTabs.Archived)
                logic.actions.loadExperiments()
            })
                .toMatchValues({
                    tab: ExperimentsTabs.Archived,
                })
                .toFinishAllListeners()

            expect(api.get).toHaveBeenCalledWith(expect.stringContaining('archived=true'))
        })

        it('constructs correct params from filters', () => {
            logic.actions.setExperimentsFilters({
                search: 'test',
                status: ProgressStatus.Running,
                page: 2,
            })

            expect(logic.values.paramsFromFilters).toEqual({
                search: 'test',
                status: ProgressStatus.Running,
                page: 2,
                limit: 100,
                offset: 100,
                archived: false,
            })
        })
    })

    describe('experiment CRUD operations', () => {
        beforeEach(() => {
            router.actions.push = jest.fn()
        })

        it('archives experiment', async () => {
            const initialExperiments = { results: [mockExperiment], count: 1 }
            logic.actions.loadExperimentsSuccess(initialExperiments)

            api.update.mockResolvedValue({})

            await expectLogic(logic, () => {
                logic.actions.archiveExperiment(mockExperiment.id as number)
            })
                .toFinishAllListeners()
                .toMatchValues({
                    experiments: expect.objectContaining({
                        results: [],
                        count: 0,
                    }),
                })

            expect(api.update).toHaveBeenCalledWith(expect.stringContaining(`/experiments/${mockExperiment.id}`), {
                archived: true,
            })
        })

        it('duplicates experiment and navigates to it', async () => {
            const duplicatedExperiment = createMockExperiment({ id: 999 })
            api.create.mockResolvedValue(duplicatedExperiment)

            const initialExperiments = { results: [mockExperiment], count: 1 }
            logic.actions.loadExperimentsSuccess(initialExperiments)

            await expectLogic(logic, () => {
                logic.actions.duplicateExperiment({ id: mockExperiment.id as number, featureFlagKey: 'new-flag' })
            }).toFinishAllListeners()

            expect(api.create).toHaveBeenCalledWith(
                expect.stringContaining(`/experiments/${mockExperiment.id}/duplicate`),
                { feature_flag_key: 'new-flag' }
            )
            expect(router.actions.push).toHaveBeenCalledWith(expect.stringContaining('/999'))
        })

        it('adds experiment to list', () => {
            const initialExperiments = { results: [mockExperiment], count: 1 }
            logic.actions.loadExperimentsSuccess(initialExperiments)

            logic.actions.addToExperiments(mockRunningExperiment)

            expect(logic.values.experiments).toEqual({
                results: [mockExperiment, mockRunningExperiment],
                count: 2,
            })
        })

        it('updates experiment in list', () => {
            const initialExperiments = { results: [mockExperiment], count: 1 }
            logic.actions.loadExperimentsSuccess(initialExperiments)

            const updatedExperiment = createMockExperiment({ name: 'Updated Name' })
            logic.actions.updateExperiments(updatedExperiment)

            expect(logic.values.experiments).toEqual({
                results: [updatedExperiment],
                count: 1,
            })
        })
    })

    describe('selectors', () => {
        it('calculates shouldShowEmptyState correctly', () => {
            logic.actions.setExperimentsFilters({
                search: undefined,
                status: 'all',
                page: 1,
                created_by_id: undefined,
                order: undefined,
            })
            logic.actions.loadExperimentsSuccess({ results: [], count: 0 })

            expect(logic.values.shouldShowEmptyState).toBe(true)

            logic.actions.loadExperimentsSuccess({ results: [mockExperiment], count: 1 })
            expect(logic.values.shouldShowEmptyState).toBe(false)

            logic.actions.setExperimentsFilters({ search: 'test' })
            expect(logic.values.shouldShowEmptyState).toBe(false)
        })

        it('calculates pagination correctly', () => {
            logic.actions.setExperimentsFilters({ page: 2 })
            logic.actions.loadExperimentsSuccess({ results: [], count: 150 })

            expect(logic.values.pagination).toEqual({
                controlled: true,
                pageSize: 100,
                currentPage: 2,
                entryCount: 150,
            })
        })
    })
})

describe('utility functions', () => {
    describe('getExperimentStatus', () => {
        it('returns Draft for experiments without start date', () => {
            expect(getExperimentStatus(mockDraftExperiment)).toBe(ProgressStatus.Draft)
        })

        it('returns Running for experiments with start date but no end date', () => {
            expect(getExperimentStatus(mockRunningExperiment)).toBe(ProgressStatus.Running)
        })

        it('returns Complete for experiments with both start and end dates', () => {
            expect(getExperimentStatus(mockExperiment)).toBe(ProgressStatus.Complete)
        })
    })

    describe('getExperimentStatusColor', () => {
        it('returns correct colors for each status', () => {
            expect(getExperimentStatusColor(ProgressStatus.Draft)).toBe('default')
            expect(getExperimentStatusColor(ProgressStatus.Running)).toBe('success')
            expect(getExperimentStatusColor(ProgressStatus.Complete)).toBe('completion')
        })
    })
})
