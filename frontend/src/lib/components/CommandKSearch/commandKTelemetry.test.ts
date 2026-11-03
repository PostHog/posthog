import type { SearchItem } from 'lib/components/Search/searchItems'

import { queryShape } from './commandKTelemetry'

const products: SearchItem[] = [
    { id: 'product-replay', name: 'Session replay', category: 'products', searchKeywords: ['recordings'] },
    { id: 'product-flags', name: 'Feature flags', category: 'products' },
]

describe('queryShape', () => {
    test.each([
        ['session replay', 'session replay'],
        ['Acme recordings', '* recordings'],
        ['jane@example.com flags', '* * * flags'],
        ['фзш', '*'],
        ['', ''],
    ])('masks every word of %s that no product name uses', (query, shape) => {
        expect(queryShape(query, [products])).toEqual(shape)
    })
})
