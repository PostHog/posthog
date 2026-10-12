import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { fireEvent, render, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
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
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/unread_count': () => [200, { count: 3 }],
            },
        })
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

    // customIconRegistry is the only thing that puts Support's unread count in the sidebar. A row
    // that falls back to the static product icon loses the count and shows no other symptom.
    it.each<[string, string | null]>([
        ['support', '3'],
        ['feature-flags', null],
    ])('renders the icon that the %s row resolves to', async (slug, expectedCount) => {
        const { container } = render(<FlatNavProducts />)

        await waitFor(() => {
            const row = renderedProductRow(container, slug)
            expect(row.querySelector('.LemonBadge')?.textContent ?? null).toBe(expectedCount)
            expect(row.querySelector('svg')).not.toBeNull()
        })
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

    // The dashboards list scene mounts only after the navigation, so the modal opens from the URL alone
    it('opens the new dashboard modal from another page', async () => {
        router.actions.push(urls.currentProject(urls.insights()))
        const { container, findByText } = render(<FlatNavProducts />)

        await waitFor(() => renderedProductRow(container, 'dashboards'))
        fireEvent.click(container.querySelector('[data-attr="flat-nav-tool-menu-dashboards"]')!)
        fireEvent.click(await findByText('New dashboard'))

        expect(router.values.location.pathname).toBe(urls.currentProject(urls.dashboards()))
        newDashboardLogic.mount()
        expect(newDashboardLogic.values.newDashboardModalVisible).toBe(true)
    })
})
