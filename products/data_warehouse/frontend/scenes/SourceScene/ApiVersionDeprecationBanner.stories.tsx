import type { Meta, StoryObj } from '@storybook/react'

import { ApiVersionDeprecationBanner } from './SourceScene'

type Story = StoryObj<typeof ApiVersionDeprecationBanner>
const meta: Meta<typeof ApiVersionDeprecationBanner> = {
    title: 'Scenes-App/Data Warehouse/Settings/API version deprecation banner',
    component: ApiVersionDeprecationBanner,
    parameters: {
        viewMode: 'story',
        testOptions: {
            snapshotBrowsers: ['chromium'],
        },
    },
}

export default meta

export const WithSunsetDate: Story = {
    args: {
        sourceType: 'Stripe',
        deprecation: {
            version: '2024-09-30.acacia',
            sunset_at: '2026-12-31',
            default_version: '2026-02-25.clover',
        },
    },
}

export const WithoutSunsetDate: Story = {
    args: {
        sourceType: 'Klaviyo',
        deprecation: {
            version: '2024-10-15',
            sunset_at: null,
            default_version: '2024-10-15',
        },
    },
}
