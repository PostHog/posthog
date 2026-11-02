import { getNavProductItems } from '~/layout/panel-layout/navbar/tabs/navProductItems'
import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'

import { resolveStarredProducts } from './todayProductsLogic'

const productShortcut = (id: string, path: string, href?: string): FileSystemEntry =>
    ({ id, path, type: 'product', href }) as FileSystemEntry

describe('todayProductsLogic', () => {
    it('resolves product stars in saved order, by name or by link', () => {
        const candidates: FileSystemImport[] = getNavProductItems({})
        const shortcuts = [
            productShortcut('1', 'Session replay'),
            // Stars made by the backend have no href, so they match by name.
            productShortcut('2', 'Product analytics'),
            { id: '3', path: 'Weekly signups', type: 'insight', ref: 'abc', href: '/insights/abc' } as FileSystemEntry,
            productShortcut('4', 'Old name', '/replay/home'),
            productShortcut('5', 'Not a product'),
        ]

        expect(resolveStarredProducts(shortcuts, candidates).map((item) => item.path)).toEqual([
            'Session replay',
            'Product analytics',
        ])
    })
})
