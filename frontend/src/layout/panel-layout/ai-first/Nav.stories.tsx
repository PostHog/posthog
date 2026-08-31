import './Nav.scss'

import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { NavSearchBar } from 'lib/components/NavSearchButton/NavSearchButton'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { mswDecorator } from '~/mocks/browser'
import { SidebarDensity } from '~/queries/schema/schema-general'

import { customProductsLogic } from '../ProjectTree/customProductsLogic'
import { NavTabBrowse } from './tabs/NavTabBrowse'

/** Enough tools, across enough categories, for "My tools" to show its category headers. */
const MOCK_TOOLS = [
    'Product analytics',
    'Web analytics',
    'Session replay',
    'Surveys',
    'Error tracking',
    'Experiments',
    'Feature flags',
].map((productPath, index) => ({
    id: `product-${index}`,
    product_path: productPath,
    enabled: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
}))

/**
 * Density comes from `data-nav-density`, which `Nav` sets from the user's sidebar setting.
 * Setting the attribute here keeps the story independent of the user API.
 */
function NavSidebar({ density }: { density: SidebarDensity }): JSX.Element {
    const { loadCustomProducts } = useActions(customProductsLogic)
    useOnMountEffect(() => loadCustomProducts())

    return (
        <div
            data-nav-density={density}
            className="flex flex-col w-[var(--project-navbar-width)] h-[640px] bg-surface-tertiary border rounded overflow-hidden"
        >
            <div className="px-2 py-1">
                <NavSearchBar toggleCommand={() => {}} />
            </div>
            <NavTabBrowse />
        </div>
    )
}

/** Both densities together, so a spacing change to one is visible against the other. */
function NavSidebarDensities(): JSX.Element {
    return (
        <div className="flex gap-4">
            <div className="flex flex-col gap-1">
                <span className="text-xs font-semibold text-secondary">Comfortable</span>
                <NavSidebar density="comfortable" />
            </div>
            <div className="flex flex-col gap-1">
                <span className="text-xs font-semibold text-secondary">Compact</span>
                <NavSidebar density="compact" />
            </div>
        </div>
    )
}

const meta: Meta<typeof NavSidebarDensities> = {
    title: 'Layout/Navigation sidebar',
    component: NavSidebarDensities,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/user_product_list': () => [200, { results: MOCK_TOOLS }],
            },
        }),
    ],
}
export default meta

export const DensityComparison: StoryObj<typeof NavSidebarDensities> = {}
