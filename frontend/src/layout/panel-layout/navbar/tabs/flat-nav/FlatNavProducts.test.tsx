import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { render, waitFor } from '@testing-library/react'

import { UserProductListItem } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AppContext, TeamType } from '~/types'

import { FlatNavProducts } from './FlatNavProducts'

const productRow = (productPath: string): UserProductListItem => ({
    id: `id-${productPath}`,
    product_path: productPath,
    enabled: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
})

function renderedProductRow(container: HTMLElement, slug: string): HTMLElement {
    const row = container.querySelector<HTMLElement>(`[data-attr="flat-nav-tool-${slug}"]`)
    if (!row) {
        throw new Error(`No flat-nav row rendered for "${slug}"`)
    }
    return row
}

describe('FlatNavProducts', () => {
    beforeEach(() => {
        // customProductsLogic seeds the picked products from the page context rather than fetching them
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            custom_products: [
                productRow('Support'),
                productRow('Feature flags'),
                productRow('Dashboards'),
                productRow('Product analytics'),
                productRow('Session replay'),
            ],
        } as AppContext
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, conversations_enabled: true } as TeamType)
    })

    // The inline menus are keyed by product path, so a path that stops matching silently drops
    // the button from the row
    it.each<[string, string | null]>([
        ['dashboards', 'flat-nav-tool-menu-dashboards'],
        ['product-analytics', 'flat-nav-tool-menu-insight'],
        ['session-replay', 'flat-nav-tool-menu-session-replay'],
        ['feature-flags', null],
    ])('renders the inline menu button the %s row resolves to', async (slug, menuAttr) => {
        const { container } = render(<FlatNavProducts />)

        await waitFor(() => {
            const row = renderedProductRow(container, slug)
            const menuButton = row.parentElement?.querySelector('[data-attr^="flat-nav-tool-menu-"]')
            expect(menuButton?.getAttribute('data-attr') ?? null).toBe(menuAttr)
        })
    })
})
