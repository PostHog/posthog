import { Meta } from '@storybook/react'
import recordings from './__mocks__/recordings.json'
import { useEffect } from 'react'
import { mswDecorator } from '~/mocks/browser'
import { combineUrl, router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import recordingMetaJson from 'scenes/session-recordings/__mocks__/recording_meta.json'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import recording_playlists from './__mocks__/recording_playlists.json'

const meta: Meta = {
    title: 'Scenes-App/Recordings',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        waitForSelector: '.PlayerFrame__content .replayer-wrapper iframe',
        testOptions: { skip: true }, // TODO: Fix the flakey rendering due to player playback
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
                '/api/projects/:team_id/session_recording_playlists/:playlist_id': (req) => {
                    const playlistId = req.params.playlist_id

                    return [
                        200,
                        {
                            id: 29,
                            short_id: playlistId,
                            name: 'I am a playlist',
                            derived_name: '(Untitled)',
                            description: '',
                            pinned: false,
                            created_at: '2023-07-31T16:24:38.956943Z',
                            created_by: {
                                id: 1,
                                uuid: '01896512-b4e6-0000-3add-7143ff5174c5',
                                distinct_id: 'qs3Sp9pxE3nC827IbjDB6qNW6pD22X4tmGWwonM20p7',
                                first_name: 'paul',
                                email: 'paul@posthog.com',
                                is_email_verified: true,
                            },
                            deleted: false,
                            filters: {
                                events: [],
                                actions: [],
                                date_to: null,
                                date_from: '-7d',
                                properties: [],
                                console_logs: [],
                                session_recording_duration: {
                                    key: 'duration',
                                    type: 'recording',
                                    value: 60,
                                    operator: 'gt',
                                },
                            },
                            last_modified_at: '2023-07-31T16:34:15.297322Z',
                            last_modified_by: {
                                id: 1,
                                uuid: '01896512-b4e6-0000-3add-7143ff5174c5',
                                distinct_id: 'qs3Sp9pxE3nC827IbjDB6qNW6pD22X4tmGWwonM20p7',
                                first_name: 'paul',
                                email: 'paul@posthog.com',
                                is_email_verified: true,
                            },
                        },
                    ]
                },
                '/api/projects/:team_id/session_recording_playlists/:playlist_id/recordings': (req) => {
                    const playlistId = req.params.playlist_id
                    const response = playlistId === '1234567' ? recordings : []
                    return [200, { has_next: false, results: response, version: 1 }]
                },
                // without the session-recording-blob-replay feature flag, we only load via ClickHouse
                '/api/projects/:team/session_recordings/:id/snapshots': (req, res, ctx) => {
                    // with no sources, returns sources...
                    if (req.url.searchParams.get('source') === 'blob') {
                        return res(ctx.text(snapshotsAsJSONLines()))
                    }
                    // with no source requested should return sources
                    return [
                        200,
                        {
                            sources: [
                                {
                                    source: 'blob',
                                    start_timestamp: '2023-08-11T12:03:36.097000Z',
                                    end_timestamp: '2023-08-11T12:04:52.268000Z',
                                    blob_key: '1691755416097-1691755492268',
                                },
                            ],
                        },
                    ]
                },
                '/api/projects/:team/session_recordings/:id': recordingMetaJson,
                'api/projects/:team/notebooks': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
            },
            post: {
                '/api/projects/:team/query': recordingEventsJson,
            },
        }),
    ],
}
export default meta

export function RecentRecordings(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.replay())
    }, [])
    return <App />
}

export function RecordingsPlayListNoPinnedRecordings(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.replayPlaylist('abcdefg'))
    }, [])
    return <App />
}

export function RecordingsPlayListWithPinnedRecordings(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.replayPlaylist('1234567'))
    }, [])
    return <App />
}

export function SecondRecordingInList(): JSX.Element {
    useEffect(() => {
        router.actions.push(combineUrl(urls.replay(), undefined, { sessionRecordingId: recordings[1].id }).url)
    }, [])
    return <App />
}
