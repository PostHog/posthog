import { Meta } from '@storybook/react'
import { useEffect } from 'react'
import { mswDecorator } from '~/mocks/browser'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'
import recording_playlists from './__mocks__/recording_playlists.json'
import { ReplayTabs } from '~/types'
import recordings from 'scenes/session-recordings/__mocks__/recordings.json'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'

const meta: Meta = {
    title: 'Scenes-App/Recordings',
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
