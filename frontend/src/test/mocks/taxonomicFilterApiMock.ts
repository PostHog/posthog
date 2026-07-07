/**
 * Partial `lib/api` mock for component tests that render the TaxonomicFilter tree.
 *
 * Mounting the taxonomic filter pulls in models whose afterMount loaders call
 * namespaced `api.*` methods (actionsModel, cohortsModel, dataWarehouseViewsLogic,
 * joinsLogic, surveyQuestionLabelsLogic, ...). A hand-rolled partial mock that
 * misses one namespace makes those loaders throw on every mount, and kea-loaders
 * dumps each failure to the console. Keep the namespace floor complete here;
 * tests override individual methods via `jest.requireMock('lib/api')`.
 *
 * Response shapes mirror the real `lib/api` methods so loaders that destructure
 * (`response.results`, `response.labels`, ...) resolve cleanly to empty data.
 */

type PaginatedResponse = { results: unknown[]; count: number; next: null }

export const emptyPaginated = (): Promise<PaginatedResponse> => Promise.resolve({ results: [], count: 0, next: null })

export function buildTaxonomicFilterApiMock(overrides: Record<string, unknown> = {}): {
    __esModule: boolean
    default: Record<string, unknown>
} {
    return {
        __esModule: true,
        default: {
            get: jest.fn().mockImplementation(emptyPaginated),
            actions: { list: jest.fn().mockImplementation(emptyPaginated) },
            cohorts: { listPaginated: jest.fn().mockImplementation(emptyPaginated) },
            dashboards: { list: jest.fn().mockImplementation(emptyPaginated) },
            queryTabState: { list: jest.fn().mockImplementation(emptyPaginated) },
            dataWarehouseTables: { list: jest.fn().mockImplementation(emptyPaginated) },
            dataWarehouseSavedQueries: { list: jest.fn().mockImplementation(emptyPaginated) },
            // Returns a plain array, not a paginated envelope
            dataWarehouseSavedQueryFolders: { list: jest.fn().mockResolvedValue([]) },
            dataWarehouseViewLinks: { list: jest.fn().mockImplementation(emptyPaginated) },
            surveys: { questionLabels: jest.fn().mockResolvedValue({ labels: [] }) },
            ...overrides,
        },
    }
}
