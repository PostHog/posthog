import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { ReplayTabs } from '~/types'

import { recordingPlaylists } from './__mocks__/recording_playlists'

const meta: Meta = {
    component: App,
    title: 'Replay/Tabs/Home/Empty',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.replay(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/stats': () => [200, { users_on_product: 42, active_recordings: 0 }],
                // No recordings match, so nothing lands in the player pane by default
                '/api/environments/:team_id/session_recordings': ({ request }) => {
                    const version = new URL(request.url).searchParams.get('version')
                    return [200, { has_next: false, results: [], version }]
                },
                '/api/projects/:team_id/session_recording_playlists': recordingPlaylists,
                'api/projects/:team/notebooks': { count: 0, next: null, previous: null, results: [] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

// Empty result set: the player pane shows the same "No matching recordings" guidance as the list
// rather than telling the user to pick from a list that has nothing in it.
export const NoMatchingRecordings: Story = {
    parameters: {
        pageUrl: urls.replay(ReplayTabs.Home),
    },
}
