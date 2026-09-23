import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { fireEvent, render, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

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

function toolRow(container: HTMLElement, slug: string): HTMLElement {
    const row = container.querySelector<HTMLElement>(`[data-attr="flat-nav-tool-${slug}"]`)
    if (!row) {
        throw new Error(`No flat-nav row rendered for "${slug}"`)
    }
    return row
}

describe('FlatNavProducts', () => {
    let bulkUpdateBodies: unknown[]

    beforeEach(() => {
        bulkUpdateBodies = []
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/unread_count': () => [200, { count: 3 }],
            },
            patch: {
                '/api/projects/:team_id/user_product_list/bulk_update/': async ({ request }) => {
                    bulkUpdateBodies.push(await request.json())
                    return [200, { results: [] }]
                },
            },
        })
        // customProductsLogic seeds the picked tools from the page context rather than fetching them
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
            const row = toolRow(container, slug)
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
            const row = toolRow(container, slug)
            const menuButton = row.parentElement?.querySelector('[data-attr^="flat-nav-tool-menu-"]')
            expect(menuButton?.getAttribute('data-attr') ?? null).toBe(menuAttr)
        })
    })

    it.each<[string, string | null]>([
        [urls.workflows(), 'workflows'],
        ['/workflows/broadcasts', 'broadcasts'],
        [urls.featureFlag(1), null],
        [urls.settings(), null],
    ])('on %s puts the pin button on this row: %s', async (url, pinnedSlug) => {
        router.actions.push(url)
        const { container } = render(<FlatNavProducts />)

        await waitFor(() => toolRow(container, 'feature-flags'))
        const pinnedRows = Array.from(container.querySelectorAll('[data-attr="flat-nav-tool-pin"]')).map((pinButton) =>
            pinButton.previousElementSibling?.getAttribute('data-attr')
        )
        expect(pinnedRows).toEqual(pinnedSlug ? [`flat-nav-tool-${pinnedSlug}`] : [])
    })

    it('pins the tool of the current page and keeps its row', async () => {
        router.actions.push(urls.workflows())
        const { container } = render(<FlatNavProducts />)

        const pinButton = await waitFor(() => {
            const button = container.querySelector<HTMLElement>('[data-attr="flat-nav-tool-pin"]')
            expect(button).not.toBeNull()
            return button as HTMLElement
        })
        fireEvent.click(pinButton)

        await waitFor(() => {
            expect(bulkUpdateBodies).toEqual([{ items: [{ product_path: 'Workflows', enabled: true }] }])
        })
        expect(container.querySelector('[data-attr="flat-nav-tool-pin"]')).toBeNull()
        expect(toolRow(container, 'workflows')).toBeTruthy()
    })
})
