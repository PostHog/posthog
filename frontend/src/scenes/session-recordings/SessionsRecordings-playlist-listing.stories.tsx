import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import recordings from 'scenes/session-recordings/__mocks__/recordings.json'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { ReplayTabs } from '~/types'

import recording_playlists from './__mocks__/recording_playlists.json'

const meta: Meta = {
    title: 'Replay/Listings',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/session_recording_playlists': recording_playlists,
                '/api/projects/:team_id/session_recordings': (req) => {
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
                '/api/projects/:team/query': recordingEventsJson,
            },
        }),
    ],
}
export default meta

export function RecordingsPlayLists(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.replay(ReplayTabs.Playlists))
    }, [])
    return <App />
}
