import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { ActivityTab } from '~/types'

import eventsQuery from './__mocks__/eventsQuery.json'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Events',
    decorators: [mswDecorator({})],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
        pageUrl: urls.activity(ActivityTab.ExploreEvents),
        msw: {
            mocks: {
                post: {
                    '/api/environments/:team_id/query/:kind': eventsQuery,
                },
            },
        },
    },
}
export default meta

type Story = StoryObj<{}>
export const EventExplorer: Story = {}

export const EventExplorerEmptyOutsideTimeRange: Story = {
    parameters: {
        msw: {
            mocks: {
                post: {
                    '/api/environments/:team_id/query/:kind': async (info: any) => {
                        const { query } = await info.request.json()
                        // Only the empty-state probe, which reaches back 90 days, finds a match.
                        return [200, { results: query.after === '-90d' ? [['2023-01-20T09:00:00Z']] : [], columns: [] }]
                    },
                },
            },
        },
    },
}
