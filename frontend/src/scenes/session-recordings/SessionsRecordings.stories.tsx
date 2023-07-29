import { Meta } from '@storybook/react'
import recordings from './__mocks__/recordings.json'
import { useEffect } from 'react'
import { mswDecorator } from '~/mocks/browser'
import { combineUrl, router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'
import recordingSnapshotsJson from 'scenes/session-recordings/__mocks__/recording_snapshots.json'
import recordingMetaJson from 'scenes/session-recordings/__mocks__/recording_meta.json'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import recording_playlists from './__mocks__/recording_playlists.json'
import { ReplayTabs } from '~/types'

export default {
    title: 'Scenes-App/Recordings',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
        mockDate: '2023-02-01',
    },
    decorators: [
        mswDecorator({
            get: {
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
                '/api/projects/:team_id/session_recording_playlists': recording_playlists,
                // without the session-recording-blob-replay feature flag, we only load via ClickHouse
                '/api/projects/:team/session_recordings/:id/snapshots': recordingSnapshotsJson,
                '/api/projects/:team/session_recordings/:id': recordingMetaJson,
            },
            post: {
                '/api/projects/:team/query': recordingEventsJson,
            },
        }),
    ],
} as Meta

export function RecordingsList(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.replay())
    }, [])
    return <App />
}

export function RecordingsPlayLists(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.replay(ReplayTabs.Playlists))
    }, [])
    return <App />
}

export function SecondRecordingInList(): JSX.Element {
    useEffect(() => {
        router.actions.push(combineUrl(urls.replay(), undefined, { sessionRecordingId: recordings[1].id }).url)
    }, [])
    return <App />
}
