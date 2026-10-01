import { filterLibraryTypes, libraryObjectHref, libraryObjectName, libraryTypeForPath } from './libraryUtils'

describe('libraryUtils', () => {
    test.each([
        ['Unfiled/Insights/Checkout funnel', 'Checkout funnel'],
        ['Unfiled/Insights/Signups a\\/b test', 'Signups a/b test'],
        ['Top level', 'Top level'],
    ])('names %s as %s', (path, name) => {
        expect(libraryObjectName({ path })).toBe(name)
    })

    test.each([
        ['its own href first', { href: '/custom', type: 'insight', ref: 'abc' }, '/custom'],
        ['the registered page for its type', { type: 'feature_flag', ref: '7' }, '/feature_flags/7'],
        ['no link without a ref', { type: 'feature_flag' }, null],
        ['no link for an unknown type', { type: 'not_a_type', ref: '7' }, null],
    ])('links an object to %s', (_, entry, href) => {
        expect(libraryObjectHref(entry)).toBe(href)
    })

    test.each([
        ['/feature_flags/920847', 'feature_flag'],
        ['/workflows/abc/workflow', 'workflows'],
        ['/replay/playlists/abc', 'session_recording_playlist'],
        ['/feature_flags', 'feature_flag'],
        ['/dashboard', 'dashboard'],
        ['/data-management/actions', 'action'],
        ['/feature_flags/templates', null],
        ['/workflows/library/templates/new', null],
        ['/notebooks/abc', null],
    ])('finds the object type of %s', (path, type) => {
        expect(libraryTypeForPath(path)).toBe(type)
    })

    test.each([
        ['', ['feature_flag', 'dashboard']],
        ['  FLAG ', ['feature_flag']],
        ['boards', ['dashboard']],
        ['nothing', []],
    ])('filters types by %j', (search, values) => {
        const types = [
            { value: 'feature_flag', label: 'Feature flag', pluralLabel: 'Feature flags' },
            { value: 'dashboard', label: 'Dashboard', pluralLabel: 'Dashboards' },
        ]
        expect(filterLibraryTypes(types, search).map((type) => type.value)).toEqual(values)
    })
})
