import { buildFilterOptions, viewAllFor } from './commandKFilterOptions'
import { FilterOptions, QueryChip, ResolvedQuery, resolveQuery } from './commandKQuery'

const chip = (value: string, label: string, overrides: Partial<QueryChip> = {}): QueryChip => ({
    key: 'is',
    value,
    label,
    negated: false,
    ...overrides,
})

const NO_OPTIONS: FilterOptions = { is: [], createdBy: [], in: [], name: [] }

const resolved = (filters: QueryChip[], freeText = ''): ResolvedQuery => resolveQuery(freeText, filters, NO_OPTIONS)

const createdByMe = chip('me', 'Me', { key: 'createdBy' })

describe('viewAllFor', () => {
    test.each([
        [
            'a manifest list page',
            [chip('feature_flag', 'Feature flag')],
            '',
            'View all feature flags',
            '/feature-flags',
        ],
        ['a type with a fallback page', [chip('dashboard', 'Dashboard')], '', 'View all dashboards', '/dashboard'],
        [
            'other filters alongside',
            [chip('feature_flag', 'Feature flag'), createdByMe],
            '',
            'View all feature flags',
            '/feature-flags',
        ],
        [
            'a list that searches the text but not the filters',
            [chip('feature_flag', 'Feature flag'), createdByMe],
            'checkout v2',
            'View all feature flags',
            '/feature-flags?search=checkout%20v2',
        ],
        [
            'a list that searches quoted text without its quotes',
            [chip('feature_flag', 'Feature flag')],
            '"checkout v2" beta',
            'View all feature flags',
            '/feature-flags?search=checkout%20v2%20beta',
        ],
        [
            'a list that searches a word quoted midway without its quotes',
            [chip('feature_flag', 'Feature flag')],
            'checkout" v2" beta',
            'View all feature flags',
            '/feature-flags?search=checkout%20v2%20beta',
        ],
        [
            'a list that searches without the excluded words',
            [chip('feature_flag', 'Feature flag')],
            'beta -legacy -"old flow" !draft - "" "-wip" "-"',
            'View all feature flags',
            '/feature-flags?search=beta',
        ],
        [
            'a list that searches without single-quoted excluded words',
            [chip('feature_flag', 'Feature flag')],
            "checkout '-legacy' 'v2 beta'",
            'View all feature flags',
            '/feature-flags?search=checkout%20v2%20beta',
        ],
        [
            'a list that keeps an apostrophe the search reads as a letter',
            [chip('feature_flag', 'Feature flag')],
            "don't -legacy",
            'View all feature flags',
            "/feature-flags?search=don't",
        ],
        [
            'a list that keeps an unclosed double quote the search reads as a letter',
            [chip('feature_flag', 'Feature flag')],
            'a"b -legacy',
            'View all feature flags',
            '/feature-flags?search=a%22b',
        ],
        [
            'a list that searches the name filter before the text',
            [chip('feature_flag', 'Feature flag'), chip('checkout', 'checkout', { key: 'name' })],
            'beta',
            'View all feature flags',
            '/feature-flags?search=checkout%20beta',
        ],
        [
            'a list that searches a single-quoted name without its quotes',
            [chip('feature_flag', 'Feature flag')],
            "name:'checkout' beta",
            'View all feature flags',
            '/feature-flags?search=checkout%20beta',
        ],
        [
            'a list that reads every quote as a letter once one quote in the query is unmatched',
            [chip('feature_flag', 'Feature flag')],
            "name:rock'n'roll -don't",
            'View all feature flags',
            "/feature-flags?search=rock'n'roll",
        ],
        [
            'a list that reads the text as a letter when the name holds the unmatched quote',
            [chip('feature_flag', 'Feature flag')],
            "name:don't rock'n'roll",
            'View all feature flags',
            "/feature-flags?search=don't%20rock'n'roll",
        ],
        [
            'a list that searches without an excluded name',
            [chip('feature_flag', 'Feature flag'), chip('checkout', 'checkout', { key: 'name', negated: true })],
            '',
            'View all feature flags',
            '/feature-flags',
        ],
        [
            'a fallback page that searches the text',
            [chip('dashboard', 'Dashboard')],
            'revenue',
            'View all dashboards',
            '/dashboard?search=revenue',
        ],
        [
            'a list that reads no query',
            [chip('action', 'Action'), createdByMe],
            'signup',
            'View all actions',
            '/data-management/actions',
        ],
    ])('names the list page for %s', (_, chips, freeText, name, href) => {
        expect(viewAllFor(resolved(chips, freeText))?.item).toMatchObject({ name, href })
    })

    test.each([
        ['alert', 'alert', 'View all alerts', '/alerts'],
        ['ticket', 'ticket', 'View all tickets', '/support/tickets'],
        ['destination', 'hog_function/destination', 'View all destinations', '/data-management/destinations'],
        [
            'transformation',
            'hog_function/transformation',
            'View all transformations',
            '/data-management/transformations',
        ],
        ['endpoint', 'endpoints', 'View all endpoints', '/endpoints'],
    ])('resolves is:%s to its type and names its list page', (typed, value, name, href) => {
        const typedQuery = resolveQuery(`is:${typed}`, [], buildFilterOptions([], null, []))
        expect(typedQuery.filters).toEqual([expect.objectContaining({ key: 'is', value, negated: false })])
        expect(viewAllFor(typedQuery)?.item).toMatchObject({ name, href })
    })

    test.each([
        ['leads with only filters', '', 'lead'],
        ['trails once there is search text', 'beta', 'trail'],
    ])('%s', (_, freeText, placement) => {
        expect(viewAllFor(resolved([chip('feature_flag', 'Feature flag')], freeText))?.placement).toBe(placement)
    })

    test.each([
        ['no is chip', [createdByMe]],
        ['a negated is chip', [chip('feature_flag', 'Feature flag', { negated: true })]],
        ['a type with no list page', [chip('folder', 'Folder')]],
    ])('returns nothing for %s', (_, chips) => {
        expect(viewAllFor(resolved(chips))).toBeNull()
    })
})
