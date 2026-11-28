import { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'

import { FEATURE_FLAGS, STORYBOOK_FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { expect, userEvent } from 'storybook/test'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.dataWarehouseManagedViewsets(),
        featureFlags: [FEATURE_FLAGS.MANAGED_VIEWSETS],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/managed_viewsets/': () => {
                    return [
                        200,
                        {
                            revenue_analytics: {
                                enabled: true,
                                views: [
                                    {
                                        name: 'revenue_events',
                                        description: 'Revenue events with optimized structure',
                                        materialized: true,
                                        last_materialized: '2024-01-15T10:30:00Z',
                                    },
                                    {
                                        name: 'revenue_events_daily',
                                        description: 'Daily aggregated revenue metrics',
                                        materialized: true,
                                        last_materialized: '2024-01-15T10:30:00Z',
                                    },
                                ],
                            },
                        },
                    ]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const DataWarehouseManagedViewsets: Story = {}

const REVENUE_VIEWS = {
    count: 2,
    views: [
        { id: 'view-1', name: 'stripe.charge_revenue_view' },
        { id: 'view-2', name: 'stripe.customer_revenue_view' },
    ],
}

export const DataWarehouseManagedViewsetsQuill: Story = {
    parameters: {
        featureFlags: [...STORYBOOK_FEATURE_FLAGS, FEATURE_FLAGS.MANAGED_VIEWSETS, FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { waitForSelector: '[data-attr="managed-viewset-toggle"]', snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/managed_viewsets/revenue_analytics/': REVENUE_VIEWS,
                '/api/environments/:team_id/managed_viewsets/revenue_analytics/': REVENUE_VIEWS,
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const toggle = await canvas.findByRole('switch', { name: 'Enabled' })
        await userEvent.click(toggle)
        // The impact dialog portals to the body, outside the story canvas.
        const body = within(canvasElement.ownerDocument.body)
        await waitFor(() => expect(body.getByRole('alertdialog')).toBeInTheDocument())
        await waitFor(() => expect(body.getByText('stripe.charge_revenue_view')).toBeInTheDocument())
    },
}
