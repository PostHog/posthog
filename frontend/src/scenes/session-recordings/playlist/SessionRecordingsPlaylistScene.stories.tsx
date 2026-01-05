import { Meta, StoryFn } from '@storybook/react'
import { combineUrl, router } from 'kea-router'

import { App } from 'scenes/App'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { PropertyFilterType, PropertyOperator, SessionRecordingPlaylistType } from '~/types'

import { recordings } from '../__mocks__/recordings'

const playlistWithRecordings: SessionRecordingPlaylistType = {
    id: 99,
    short_id: 'playlist-test-123',
    name: 'Test Playlist for Storybook',
    derived_name: 'Test Playlist',
    description: 'A test playlist with recordings',
    pinned: true,
    type: 'collection',
    created_at: '2023-07-01T10:00:00.000000Z',
    created_by: {
        id: 1,
        uuid: '01896512-b4e6-0000-3add-7143ff5174c5',
        distinct_id: 'test-user-distinct-id',
        first_name: 'Test User',
        email: 'test@posthog.com',
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
            type: PropertyFilterType.Recording,
            value: 30,
            operator: PropertyOperator.GreaterThan,
        },
    },
    last_modified_at: '2023-07-04T12:00:00.000000Z',
    last_modified_by: {
        id: 1,
        uuid: '01896512-b4e6-0000-3add-7143ff5174c5',
        distinct_id: 'test-user-distinct-id',
        first_name: 'Test User',
        email: 'test@posthog.com',
        is_email_verified: true,
    },
    recordings_counts: {
        saved_filters: {
            count: 3,
            watched_count: 1,
            has_more: false,
            increased: false,
        },
        collection: {
            count: 3,
            watched_count: 1,
        },
    },
}

const sceneUrl = (url: string, searchParams: Record<string, any> = {}): string =>
    combineUrl(url, {
        pause: true,
        inspectorSideBar: true,
        tab: 'inspector',
        ...searchParams,
    }).url

const meta: Meta = {
    component: App,
    title: 'Replay/Tabs/Playlist',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04',
        testOptions: {
            loaderTimeout: 15000,
            waitForSelector: '.PlayerFrame__content .replayer-wrapper iframe',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/stats': () => [200, { users_on_product: 42, active_recordings: 7 }],
                '/api/environments/:team_id/session_recordings': () => [
                    200,
                    { has_next: false, results: recordings, version: '1' },
                ],
                '/api/projects/:team_id/session_recording_playlists/:playlist_id': () => [200, playlistWithRecordings],
                '/api/projects/:team_id/session_recording_playlists/:playlist_id/recordings': () => [
                    200,
                    { has_next: false, results: recordings, version: 1 },
                ],
                '/api/environments/:team_id/session_recordings/:id/snapshots': (req, res, ctx) => {
                    if (req.url.searchParams.get('source') === 'blob_v2') {
                        return res(ctx.text(snapshotsAsJSONLines()))
                    }
                    return [
                        200,
                        {
                            sources: [
                                {
                                    source: 'blob_v2',
                                    start_timestamp: '2023-08-11T12:03:36.097000Z',
                                    end_timestamp: '2023-08-11T12:04:52.268000Z',
                                    blob_key: '0',
                                },
                            ],
                        },
                    ]
                },
                '/api/environments/:team_id/session_recordings/:id': () => [
                    200,
                    { ...recordingMetaJson, id: recordings[0].id },
                ],
                'api/projects/:team/notebooks': { count: 0, next: null, previous: null, results: [] },
            },
            patch: {
                '/api/projects/:team_id/session_recording_playlists/:playlist_id': (req) => {
                    const body = req.body as Partial<SessionRecordingPlaylistType>
                    return [200, { ...playlistWithRecordings, ...body }]
                },
            },
            post: {
                '/api/projects/:team_id/session_recording_playlists/:playlist_id/playlist_viewed': [
                    200,
                    { success: true },
                ],
                '/api/environments/:team_id/session_recording_playlists/:playlist_id/playlist_viewed': [
                    200,
                    { success: true },
                ],
                '/api/environments/:team_id/query': (req, res, ctx) => {
                    const body = req.body as Record<string, any>

                    if (body.query.kind === 'EventsQuery') {
                        return res(ctx.json(recordingEventsJson))
                    }

                    if (
                        body.query.kind === 'HogQLQuery' &&
                        body.query.query.includes('any(properties.$geoip_country_code) as $geoip_country_code')
                    ) {
                        return res(
                            ctx.json({
                                columns: [
                                    'session_id',
                                    '$geoip_country_code',
                                    '$browser',
                                    '$device_type',
                                    '$os',
                                    '$os_name',
                                    '$entry_referring_domain',
                                    '$geoip_subdivision_1_name',
                                    '$geoip_city_name',
                                    '$entry_current_url',
                                ],
                                results: recordings.map((recording) => [
                                    recording.id,
                                    'GB',
                                    'Chrome',
                                    'Desktop',
                                    'Mac OS X',
                                    '',
                                    'posthog.com',
                                    'England',
                                    'London',
                                    'https://posthog.com/entry-page',
                                ]),
                            })
                        )
                    }

                    return res(ctx.json({ results: [] }))
                },
            },
        }),
    ],
}
export default meta

export const PlaylistWide: StoryFn = () => {
    router.actions.push(sceneUrl(urls.replayPlaylist('playlist-test-123'), { sessionRecordingId: recordings[0].id }))

    return <App />
}
PlaylistWide.parameters = {
    testOptions: {
        viewport: { width: 1300, height: 720 },
    },
}
PlaylistWide.tags = ['test-skip']

export const PlaylistNarrow: StoryFn = () => {
    router.actions.push(sceneUrl(urls.replayPlaylist('playlist-test-123'), { sessionRecordingId: recordings[0].id }))

    return <App />
}
PlaylistNarrow.parameters = {
    testOptions: {
        viewport: { width: 568, height: 1024 },
    },
}
PlaylistNarrow.tags = ['test-skip']
