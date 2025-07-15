import { Meta, StoryObj } from '@storybook/react'
import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordings } from 'scenes/session-recordings/__mocks__/recordings'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { ReplayTabs } from '~/types'

import { recordingPlaylists } from './__mocks__/recording_playlists'

const meta: Meta = {
    component: App,
    title: 'Replay/Tabs/Collections',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.replay(ReplayTabs.Playlists),
        featureFlags: [FEATURE_FLAGS.SESSION_RECORDINGS_PLAYLIST_COUNT_COLUMN],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/session_recording_playlists': recordingPlaylists,
                '/api/environments/:team_id/session_recordings': (req) => {
                    const version = req.url.searchParams.get('version')
                    return [
                        200,
                        {
                            has_next: false,
                            results: recordings,
                            version,
                        },
                    ]
                },
            },
            post: {
                '/api/environments/:team_id/query': recordingEventsJson,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const RecordingsPlayLists: Story = {}
