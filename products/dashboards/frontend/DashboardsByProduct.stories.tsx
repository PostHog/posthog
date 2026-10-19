import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { DashboardsByProduct } from './DashboardsByProduct'

const meta: Meta<typeof DashboardsByProduct> = {
    title: 'Products/Dashboards/Dashboards by product',
    component: DashboardsByProduct,
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
    decorators: [
        (Story) => (
            <div className="w-130">
                <Story />
            </div>
        ),
    ],
}
export const FlagOff: Story = {
    parameters: { featureFlags: [] },
}
