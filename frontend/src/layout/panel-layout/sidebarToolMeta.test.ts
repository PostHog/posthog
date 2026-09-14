import { SIDEBAR_TOOLS_WITHOUT_DOCS, sidebarToolMeta } from '~/layout/panel-layout/sidebarToolMeta'
import { getTreeItemsProducts } from '~/products'

describe('sidebarToolMeta', () => {
    const products = getTreeItemsProducts()

    it.each(products.map((product) => [product.path, product] as const))(
        '%s explains itself in sidebar settings',
        (path, product) => {
            const { description, docsHref } = sidebarToolMeta(product)
            expect(description).toBeTruthy()
            if (!SIDEBAR_TOOLS_WITHOUT_DOCS.has(path)) {
                expect(docsHref).toMatch(/^https:\/\/posthog\.com\/docs\//)
            }
        }
    )

    it('only exempts tools that are still missing a docs page', () => {
        const stale = [...SIDEBAR_TOOLS_WITHOUT_DOCS].filter((path) => {
            const product = products.find((candidate) => candidate.path === path)
            return !product || sidebarToolMeta(product).docsHref
        })
        expect(stale).toEqual([])
    })
})
