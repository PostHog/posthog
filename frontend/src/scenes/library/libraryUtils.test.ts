import { libraryObjectHref, libraryObjectName } from './libraryUtils'

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
})
