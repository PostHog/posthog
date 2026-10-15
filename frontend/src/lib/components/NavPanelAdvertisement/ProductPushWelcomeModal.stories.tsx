import type { Meta, StoryObj } from '@storybook/react'

import { ProductKey } from '~/queries/schema/schema-general'

import { dashboardsEmptyState } from 'products/dashboards/frontend/emptyState/dashboardsEmptyState'
import { productAnalyticsEmptyState } from 'products/product_analytics/frontend/emptyState/productAnalyticsEmptyState'

import type { PendingProductPushWelcome } from './navPanelProductPushWelcomeVisibility'
import { ProductPushWelcomeModal } from './ProductPushWelcomeModal'

const meta = {
    title: 'Components/ProductPushWelcomeModal',
    component: ProductPushWelcomeModal,
    parameters: { layout: 'fullscreen', viewMode: 'story' },
} satisfies Meta<typeof ProductPushWelcomeModal>

export default meta
type Story = StoryObj<typeof meta>

const welcomeFor = (productKey: ProductKey, label: string, text: string): PendingProductPushWelcome => ({
    campaignId: 'campaign-1',
    productKey,
    label,
    text,
})

// The product the modal exists for: every project sends events, so its setup screen never shows.
export const ProductAnalytics: Story = {
    args: {
        welcome: welcomeFor(ProductKey.PRODUCT_ANALYTICS, 'Product analytics', 'Insights, funnels, trends.'),
        config: productAnalyticsEmptyState.config,
        onClose: () => {},
    },
}

// Projects are created with dashboards already in them, so this one hides the same way.
export const Dashboards: Story = {
    args: {
        welcome: welcomeFor(ProductKey.DASHBOARDS, 'Dashboards', 'Every number your team checks, on one page.'),
        config: dashboardsEmptyState.config,
        onClose: () => {},
    },
}

// The fallback shape, for a push whose scene has no setup screen to take copy from.
export const FallbackToCardCopy: Story = {
    args: {
        welcome: welcomeFor(
            ProductKey.SESSION_REPLAY,
            'Session replay',
            'Your team logs a lot of errors. Watch the sessions they happened in.'
        ),
        onClose: () => {},
    },
}
