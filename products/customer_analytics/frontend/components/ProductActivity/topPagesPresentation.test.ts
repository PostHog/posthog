import type { AccountTopPage, AccountTopPagesResult } from '~/queries/schema/schema-general'

import { filterTopPages, getTopPagesProductOptions } from './topPagesPresentation'

function page(path: string, product: string, views: number): AccountTopPage {
    return { path, title: '', product, views, people: 1, activeDays: 1, lastViewed: '2026-11-01T00:00:00Z' }
}

const RESULT: AccountTopPagesResult = {
    columns: [],
    truncated: false,
    products: [
        { key: 'pa', label: 'Product analytics' },
        { key: 'flags', label: 'Feature flags' },
    ],
    pages: [
        page('/dashboard/1', 'pa', 5),
        page('/new-area', '', 40),
        page('/feature_flags/2', 'flags', 9),
        page('/insights/a', 'pa', 6),
    ],
}

describe('topPagesPresentation', () => {
    it('lists products by views and keeps unowned pages last', () => {
        expect(getTopPagesProductOptions(RESULT)).toEqual([
            { key: 'pa', label: 'Product analytics', views: 11 },
            { key: 'flags', label: 'Feature flags', views: 9 },
            { key: 'other', label: 'Other pages', views: 40 },
        ])
    })

    it.each([
        [null, ['/dashboard/1', '/new-area', '/feature_flags/2', '/insights/a']],
        ['pa', ['/dashboard/1', '/insights/a']],
        ['other', ['/new-area']],
    ])('filters pages to %s', (productKey, expected) => {
        expect(filterTopPages(RESULT.pages, productKey).map(({ path }) => path)).toEqual(expected)
    })
})
