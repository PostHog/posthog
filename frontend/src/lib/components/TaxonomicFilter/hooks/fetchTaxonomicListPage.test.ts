import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { fetchTaxonomicListPage } from './fetchTaxonomicListPage'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: { get: jest.fn().mockResolvedValue({ results: [], count: 0 }) },
}))

const apiGet = jest.requireMock('lib/api').default.get as jest.Mock

function group(type: TaxonomicFilterGroupType): TaxonomicFilterGroup {
    return { type, name: type, endpoint: `api/projects/1/${type}`, searchAlias: 'search' } as TaxonomicFilterGroup
}

describe('fetchTaxonomicListPage exclude_stale', () => {
    beforeEach(() => apiGet.mockClear())

    const cases: [string, TaxonomicFilterGroupType, boolean, boolean][] = [
        ['events + excludeStale', TaxonomicFilterGroupType.Events, true, true],
        ['custom-events + excludeStale', TaxonomicFilterGroupType.CustomEvents, true, true],
        ['events without excludeStale', TaxonomicFilterGroupType.Events, false, false],
        ['non-event group + excludeStale', TaxonomicFilterGroupType.EventProperties, true, false],
    ]
    it.each(cases)('%s -> exclude_stale present=%s', async (_label, groupType, excludeStale, present) => {
        await fetchTaxonomicListPage({
            group: group(groupType),
            searchQuery: 'foo',
            offset: 0,
            limit: 100,
            isExpanded: false,
            excludeStale,
        })

        const url = apiGet.mock.calls[0][0] as string
        expect(url.includes('exclude_stale=true')).toBe(present)
    })
})
