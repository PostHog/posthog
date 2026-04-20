import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { JOURNEY_FEATURE_FLAGS } from 'scenes/funnels/FunnelFlowGraph/__mocks__/journeyMocks'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Customer Analytics/Journey Builder',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15',
        featureFlags: JOURNEY_FEATURE_FLAGS,
    },
    decorators: [
        mswDecorator({
            get: {
                'api/environments/:team_id/customer_profile_configs/': { count: 0, results: [] },
                'api/environments/:team_id/customer_journeys/': { count: 0, results: [] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const NewJourney: Story = {
    render: () => {
        return <App />
    },
    parameters: {
        pageUrl: urls.customerJourneyBuilder(),
        testOptions: { waitForSelector: '[data-attr="scene-title-textarea"]' },
    },
}
