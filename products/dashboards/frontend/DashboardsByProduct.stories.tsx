import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { DashboardsByProduct } from './DashboardsByProduct'

const meta: Meta<typeof DashboardsByProduct> = {
    title: 'Products/Dashboards/Dashboards by product',
    component: DashboardsByProduct,
    decorators: [
        (Story, { parameters }) => (
            <div className="min-h-20" style={{ width: parameters.containerWidth ?? 1200 }}>
                <Story />
            </div>
        ),
    ],
    parameters: { featureFlags: [FEATURE_FLAGS.DASHBOARDS_BY_PRODUCT, FEATURE_FLAGS.PRODUCT_ANALYTICS_HOME_TAB] },
}

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {}
export const WithoutProductAnalytics: Story = {
    parameters: { featureFlags: [FEATURE_FLAGS.DASHBOARDS_BY_PRODUCT] },
}
export const ProductAnalyticsTestVariant: Story = {
    parameters: {
        featureFlags: {
            [FEATURE_FLAGS.DASHBOARDS_BY_PRODUCT]: true,
            [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOME_TAB]: 'test',
        },
    },
}
export const ProductAnalyticsControlVariant: Story = {
    parameters: {
        featureFlags: {
            [FEATURE_FLAGS.DASHBOARDS_BY_PRODUCT]: true,
            [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOME_TAB]: 'control',
        },
    },
}
export const Narrow: Story = {
    parameters: { containerWidth: 520 },
}
export const FlagOff: Story = {
    parameters: { featureFlags: [] },
}
