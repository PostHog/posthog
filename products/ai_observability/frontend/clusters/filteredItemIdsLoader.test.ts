import api from 'lib/api'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { loadFilterMatchedItemIds } from './filteredItemIdsLoader'
import { ClusteringLevel } from './types'

jest.mock('lib/api')

const mockApi = api as jest.Mocked<typeof api>

const personFilter: AnyPropertyFilter = {
    type: PropertyFilterType.Person,
    key: 'email',
    operator: PropertyOperator.IContains,
    value: 'example.com',
}

function callLoader(
    overrides: Partial<Parameters<typeof loadFilterMatchedItemIds>[0]> = {}
): ReturnType<typeof loadFilterMatchedItemIds> {
    return loadFilterMatchedItemIds({
        itemIds: ['aaaaaaaa-0000-0000-0000-000000000001'],
        level: 'trace' as ClusteringLevel,
        windowStart: '2026-09-01T00:00:00Z',
        windowEnd: '2026-09-02T00:00:00Z',
        propertyFilters: [personFilter],
        filterTestAccounts: false,
        scene: 'AIObservabilityClusters',
        ...overrides,
    })
}

describe('loadFilterMatchedItemIds', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        mockApi.queryHogQL.mockResolvedValue({ results: [] } as any)
    })

    it('matches a trace on any of its events, not only generations', async () => {
        await callLoader()

        const [query] = mockApi.queryHogQL.mock.calls[0]
        // A trace whose window holds only spans or embeddings still has to be testable,
        // otherwise every filter empties the page.
        expect(query).toContain('$ai_span')
        expect(query).toContain('$ai_embedding')
        expect(query).toContain('$ai_trace')
        expect(query).toContain("properties.$ai_trace_id IN ['aaaaaaaa-0000-0000-0000-000000000001']")
    })

    it('matches generation items on the event uuid, which is the id clustering stores', async () => {
        await callLoader({ level: 'generation' as ClusteringLevel })

        const [query] = mockApi.queryHogQL.mock.calls[0]
        expect(query).toContain("event = '$ai_generation'")
        expect(query).toContain("uuid IN ['aaaaaaaa-0000-0000-0000-000000000001']")
        // The SDK never sets this property on the event, so matching on it finds nothing.
        expect(query).not.toContain('$ai_generation_id')
    })

    it('passes property filters and the test-account toggle to the {filters} placeholder', async () => {
        await callLoader({ filterTestAccounts: true })

        const [query, , options] = mockApi.queryHogQL.mock.calls[0]
        expect(query).toContain('{filters}')
        expect(options?.queryParams?.filters).toEqual({
            properties: [personFilter],
            filterTestAccounts: true,
        })
    })

    it('returns the matched ids', async () => {
        mockApi.queryHogQL.mockResolvedValue({ results: [['trace-a'], ['trace-b']] } as any)

        await expect(callLoader()).resolves.toEqual(new Set(['trace-a', 'trace-b']))
    })

    it.each([
        ['no filters are active', { propertyFilters: [], filterTestAccounts: false }],
        ['the run is an evaluation run', { level: 'evaluation' as ClusteringLevel }],
    ])('skips filtering and queries nothing when %s', async (_name, overrides) => {
        await expect(callLoader(overrides)).resolves.toBeNull()
        expect(mockApi.queryHogQL).not.toHaveBeenCalled()
    })
})
