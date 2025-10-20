import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

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

type Story = StoryObj<typeof meta>
export const DataWarehouseManagedViewsets: Story = {}
