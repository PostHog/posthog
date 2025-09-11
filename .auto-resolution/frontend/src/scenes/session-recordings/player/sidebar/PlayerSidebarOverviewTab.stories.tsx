import { Meta, StoryFn } from '@storybook/react'
import { BindLogic } from 'kea'

import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { recordingPlaylists } from 'scenes/session-recordings/__mocks__/recording_playlists'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { recordings } from 'scenes/session-recordings/__mocks__/recordings'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { PlayerSidebarOverviewTab } from 'scenes/session-recordings/player/sidebar/PlayerSidebarOverviewTab'

import { mswDecorator } from '~/mocks/browser'

const meta: Meta = {
    title: 'Replay/Overview Tab',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/notebooks/recording_comments': { results: [] },
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
                '/api/environments/:team_id/session_recordings/:id': (req, res, ctx) => {
                    if (req.params.id === '12345') {
                        return res(ctx.json(recordingMetaJson))
                    } else if (req.params.id === 'thirty_others') {
                        return res(
                            ctx.json({
                                ...recordingMetaJson,
                                viewers: Array.from({ length: 30 }, (_, i) => `${i}@example.com`),
                            })
                        )
                    }
                    return res(ctx.json({ ...recordingMetaJson, viewers: ['abcdefg'] }))
                },
                'api/projects/:team/notebooks': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
            },
            post: {
                '/api/environments/:team_id/query': (req, res, ctx) => {
                    const body = req.body as Record<string, any>
                    if (
                        body.query.kind === 'HogQLQuery' &&
                        // very lazy match
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
                                results: [
                                    [
                                        '187d7c7619e1d62-0a36a9481897db-1d525634-384000-187d7c7619f3d4f',
                                        'GB',
                                        'Chrome',
                                        'Desktop',
                                        'Max OS',
                                        '',
                                        'hedgehog.io',
                                        'Spikeville',
                                        'Hogington',
                                        'https://hedgehog.io/entry-page',
                                    ],
                                ],
                            })
                        )
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

interface OverviewTabProps {
    width: number
    sessionId?: string
}

const OverviewTabTemplate: StoryFn<OverviewTabProps> = ({
    width,
    sessionId = '12345',
}: {
    width: number
    sessionId?: string
}) => {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ width: `${width}px`, height: '100vh' }}>
            <BindLogic
                logic={sessionRecordingPlayerLogic}
                props={{ playerKey: 'storybook', sessionRecordingId: sessionId }}
            >
                <PlayerSidebarOverviewTab />
            </BindLogic>
        </div>
    )
}

export const NarrowOverviewTab = OverviewTabTemplate.bind({})
NarrowOverviewTab.args = { width: 320 }

export const WideOverviewTab = OverviewTabTemplate.bind({})
WideOverviewTab.args = { width: 500 }

export const OneOtherWatchersOverviewTab = OverviewTabTemplate.bind({})
OneOtherWatchersOverviewTab.args = { width: 400, sessionId: '34567' }

export const ManyOtherWatchersOverviewTab = OverviewTabTemplate.bind({})
ManyOtherWatchersOverviewTab.args = { width: 400, sessionId: 'thirty_others' }
