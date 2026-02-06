import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { FEATURE_FLAGS } from '~/lib/constants'
import { mswDecorator } from '~/mocks/browser'
import { ActivityTab } from '~/types'

import eventsQuery from './__mocks__/eventsQuery.json'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Events',
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind': eventsQuery,
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
        pageUrl: urls.activity(ActivityTab.ExploreEvents),
        featureFlags: [FEATURE_FLAGS.SESSIONS_EXPLORER],
    },
}
export default meta

type Story = StoryObj<typeof meta>
export const EventExplorer: Story = {}
