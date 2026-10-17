import { FacetGroupItem, filterFacetsByName } from './facetGroups'

const facet = (key: string, title: string, group: string): FacetGroupItem => ({ key, title, group })

const FACETS: FacetGroupItem[] = [
    facet('level', 'Level', 'Standard'),
    facet('service', 'Service', 'Standard'),
    facet('namespace', 'Namespace', 'Kubernetes'),
    facet('pod', 'Pod', 'Kubernetes'),
    facet('host', 'Host', 'Infrastructure'),
]

describe('facetGroups', () => {
    describe('filterFacetsByName', () => {
        it.each([
            ['blank query returns all', '', ['level', 'service', 'namespace', 'pod', 'host']],
            ['whitespace-only returns all', '   ', ['level', 'service', 'namespace', 'pod', 'host']],
            ['matches a field title', 'namespace', ['namespace']],
            ['title match is case-insensitive', 'NAMESPACE', ['namespace']],
            ['partial title match', 'serv', ['service']],
            ['matches a whole group by name', 'kubernetes', ['namespace', 'pod']],
            ['group match is case-insensitive', 'INFRA', ['host']],
            ['no match returns empty', 'zzz', []],
        ])('%s', (_, query, expectedKeys) => {
            expect(filterFacetsByName(FACETS, query).map((f) => f.key)).toEqual(expectedKeys)
        })
    })
})
