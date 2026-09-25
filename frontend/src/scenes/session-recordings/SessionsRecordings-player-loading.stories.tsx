import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { recordingPlaylists } from './__mocks__/recording_playlists'
import { recordings } from './__mocks__/recordings'

const meta: Meta = {
    component: App,
    title: 'Replay/Tabs/Home/Loading',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.replay(),
    },
    decorators: [
        // The recording metadata never answers, so the player holds the state it has between the
        // moment someone picks a recording and the first snapshot.
        mswDecorator({
            get: {
                '/stats': () => [200, { users_on_product: 42, active_recordings: 7 }],
                '/api/environments/:team_id/session_recordings': ({ request }) => {
                    const version = new URL(request.url).searchParams.get('version')
                    return [200, { has_next: false, results: recordings, version }]
                },
                '/api/projects/:team_id/session_recording_playlists': recordingPlaylists,
                '/api/environments/:team_id/session_recordings/:id': (): Promise<never> => new Promise(() => {}),
                'api/projects/:team/notebooks': { count: 0, next: null, previous: null, results: [] },
            },
            post: {
                '/api/environments/:team_id/query/:kind': { results: [] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const LoadingRecording: Story = {
    parameters: {
        testOptions: { waitForLoadersToDisappear: false, waitForSelector: '[data-attr="replay-overlay-loading"]' },
    },
}
