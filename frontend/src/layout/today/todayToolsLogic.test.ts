import { getToolSourceItems, isToolItem } from 'scenes/tools/toolsUtils'

import { POPULAR_PRODUCT_PATHS } from '~/layout/panel-layout/navbar/tabs/productsCatalog'
import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'

import { groupTodayProducts, starredProducts } from './todayToolsLogic'

const productShortcut = (id: string, path: string, href?: string): FileSystemEntry =>
    ({ id, path, type: 'product', href }) as FileSystemEntry

describe('todayToolsLogic', () => {
    it('groups the tools like the current navigation, with Popular first in its own order', () => {
        const groups = groupTodayProducts(getToolSourceItems().filter(isToolItem), '')
        const popular = groups[0]

        expect(popular.category).toBe('Popular')
        expect(popular.tools.length).toBeGreaterThan(0)
        expect(popular.tools.map((tool) => tool.path)).toEqual(
            POPULAR_PRODUCT_PATHS.filter((path) => popular.tools.some((tool) => tool.path === path))
        )
        expect(groups.slice(1).map((group) => group.category)).not.toContain('Workspace')
    })

    it('resolves product stars in saved order, including products that open a Library list', () => {
        const candidates: FileSystemImport[] = getToolSourceItems()
        const shortcuts = [
            productShortcut('1', 'Session replay'),
            // Stars made by the backend have no href, so they match by name.
            productShortcut('2', 'Product analytics'),
            { id: '3', path: 'Weekly signups', type: 'insight', ref: 'abc', href: '/insights/abc' } as FileSystemEntry,
            productShortcut('4', 'Old name', '/replay/home'),
            productShortcut('5', 'Not a product'),
        ]

        expect(starredProducts(shortcuts, candidates).map((item) => item.path)).toEqual([
            'Session replay',
            'Product analytics',
        ])
    })
})
