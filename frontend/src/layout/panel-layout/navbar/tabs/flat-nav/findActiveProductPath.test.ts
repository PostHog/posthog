import { FileSystemImport } from '~/queries/schema/schema-general'

import { findActiveProductPath } from './findActiveProductPath'

const PRODUCTS: FileSystemImport[] = [
    { path: 'Home', href: '/' },
    { path: 'Workflows', href: '/workflows' },
    { path: 'Broadcasts', href: '/workflows/broadcasts' },
    { path: 'Logs', href: '/logs?tab=live' },
    { path: 'Docs', href: '/docs#intro' },
    { path: 'Coming soon' },
]

describe('findActiveProductPath', () => {
    it.each<[string, string, string | null]>([
        ['an exact match', '/workflows', 'Workflows'],
        ['a trailing slash', '/workflows/', 'Workflows'],
        ['a page below the product', '/workflows/123/workflow', 'Workflows'],
        ['a project id prefix', '/project/42/workflows/123', 'Workflows'],
        ['a nested product', '/workflows/broadcasts', 'Broadcasts'],
        ['a page below a nested product', '/workflows/broadcasts/7', 'Broadcasts'],
        ['an href with a query string', '/logs', 'Logs'],
        ['an href with a hash', '/docs/getting-started', 'Docs'],
        ['the project root', '/', 'Home'],
        ['the project root with a project id', '/project/42', 'Home'],
        ['a shared prefix without a path boundary', '/workflows-legacy', null],
        ['a page no product owns', '/settings/project', null],
    ])('resolves %s', (_, pathname, expected) => {
        expect(findActiveProductPath(pathname, PRODUCTS)).toBe(expected)
    })

    it.each<[string, FileSystemImport[]]>([
        ['catalog order', PRODUCTS],
        ['reversed catalog order', [...PRODUCTS].reverse()],
    ])('picks the longest matching href in %s', (_, products) => {
        expect(findActiveProductPath('/workflows/broadcasts/7', products)).toBe('Broadcasts')
    })

    it('returns null for an empty catalog', () => {
        expect(findActiveProductPath('/workflows', [])).toBeNull()
    })
})
