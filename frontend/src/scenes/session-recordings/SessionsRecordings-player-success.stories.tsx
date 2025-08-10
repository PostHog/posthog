import { Meta, StoryObj } from '@storybook/react'
import { combineUrl } from 'kea-router'
import { App } from 'scenes/App'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { PropertyFilterType, PropertyOperator, SessionRecordingPlaylistType } from '~/types'

import { recordingPlaylists } from './__mocks__/recording_playlists'
import { recordings } from './__mocks__/recordings'

const playlist = (playlistId: string): SessionRecordingPlaylistType => {
    return {
        id: 29,
        short_id: playlistId,
        name: 'I am a playlist',
        derived_name: '(Untitled)',
        description: '',
        pinned: false,
        type: 'collection',
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
                type: PropertyFilterType.Recording,
                value: 60,
                operator: PropertyOperator.GreaterThan,
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
        recordings_counts: {
            saved_filters: {
                count: 10,
                watched_count: 4,
                has_more: true,
                increased: true,
            },
            collection: {
                count: 10,
                watched_count: 5,
            },
        },
    }
}

const sceneUrl = (url: string, searchParams: Record<string, any> = {}): string =>
    combineUrl(url, {
        pause: true,
        t: 7,
        ...searchParams,
    }).url

const meta: Meta = {
    component: App,
    title: 'Replay/Tabs/Home/Success',
    tags: ['test-skip'],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        waitForSelector: '.PlayerFrame__content .replayer-wrapper iframe',
        pageUrl: urls.replay(),
    },
    decorators: [
        mswDecorator({
            get: {
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
                '/api/projects/:team_id/session_recording_playlists': recordingPlaylists,
                '/api/projects/:team_id/session_recording_playlists/:playlist_id': (req) => {
                    const playlistId = req.params.playlist_id as string

                    return [200, playlist(playlistId)]
                },
                '/api/projects/:team_id/session_recording_playlists/:playlist_id/recordings': (req) => {
                    const playlistId = req.params.playlist_id
                    const response = playlistId === '1234567' ? recordings : []
                    return [200, { has_next: false, results: response, version: 1 }]
                },
                '/api/environments/:team_id/session_recordings/:id/snapshots': (req, res, ctx) => {
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
                '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
                'api/projects/:team/notebooks': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
            },
            patch: {
                '/api/projects/:team_id/session_recording_playlists/:playlist_id': (req) => {
                    const playlistId = req.params.playlist_id as string
                    const body = req.json() as Partial<SessionRecordingPlaylistType>
                    return [200, { ...playlist(playlistId), ...body }]
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

                    if (
                        body.query.kind === 'HogQLQuery' &&
                        body.query.query.startsWith(
                            'SELECT properties.$session_id as session_id, any(properties) as properties'
                        )
                    ) {
                        return res(ctx.json({ results: [['session_id_one', '{}']] }))
                    }

                    if (body.query.kind === 'EventsQuery' && body.query.properties.length === 1) {
                        return res(ctx.json(recordingEventsJson))
                    }

                    // default to an empty response or we duplicate information
                    return res(ctx.json({ results: [] }))
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const RecentRecordings: Story = {
    parameters: { pageUrl: sceneUrl(urls.replay()) },
}

export const RecordingsPlayListNoPinnedRecordings: Story = {
    parameters: { pageUrl: sceneUrl(urls.replayPlaylist('abcdefg')) },
}

export const RecordingsPlayListWithPinnedRecordings: Story = {
    parameters: { pageUrl: sceneUrl(urls.replayPlaylist('1234567')) },
}

export const SecondRecordingInList: Story = {
    parameters: { pageUrl: sceneUrl(urls.replay(), { sessionRecordingId: recordings[1].id }) },
}
