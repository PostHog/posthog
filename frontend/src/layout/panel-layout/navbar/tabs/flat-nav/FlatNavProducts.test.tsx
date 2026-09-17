import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { render, waitFor } from '@testing-library/react'

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
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/unread_count': () => [200, { count: 3 }],
            },
        })
        // customProductsLogic seeds the picked tools from the page context rather than fetching them
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            custom_products: [productRow('Support'), productRow('Feature flags')],
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
})
