import { SIDEBAR_PRODUCTS_WITHOUT_DOCS, sidebarProductMeta } from '~/layout/panel-layout/sidebarProductMeta'
import { getTreeItemsProducts } from '~/products'

describe('sidebarProductMeta', () => {
    const products = getTreeItemsProducts()

    it.each(products.map((product) => [product.path, product] as const))(
        '%s explains itself in sidebar settings',
        (path, product) => {
            const { description, docsHref } = sidebarProductMeta(product)
            expect(description).toBeTruthy()
            if (!SIDEBAR_PRODUCTS_WITHOUT_DOCS.has(path)) {
                expect(docsHref).toMatch(/^https:\/\/posthog\.com\/docs\//)
            }
        }
    )

    it('only exempts products that are still missing a docs page', () => {
        const stale = [...SIDEBAR_PRODUCTS_WITHOUT_DOCS].filter((path) => {
            const product = products.find((candidate) => candidate.path === path)
            return !product || sidebarProductMeta(product).docsHref
        })
        expect(stale).toEqual([])
    })
})
