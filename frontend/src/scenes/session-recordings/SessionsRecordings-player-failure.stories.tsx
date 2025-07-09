import { Meta, StoryObj } from '@storybook/react'
import { App } from 'scenes/App'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { recordingPlaylists } from './__mocks__/recording_playlists'
import { recordings } from './__mocks__/recordings'

const meta: Meta = {
    component: App,
    title: 'Replay/Tabs/Home/Failure',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.replay(),
    },
    decorators: [
        // API is set up so that everything except the call to load session recording metadata succeeds
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
                            sources:
                                req.params.id === 'past-ttl'
                                    ? [
                                          {
                                              source: 'realtime',
                                          },
                                      ]
                                    : [
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
                '/api/environments/:team_id/session_recordings/:id': (req) => {
                    return req.params.id === 'past-ttl'
                        ? [
                              200,
                              {
                                  id: 'past-ttl',
                                  viewed: true,
                                  viewers: ['123456'],
                                  recording_duration: 1172.675,
                                  start_time: '2021-10-04T05:19:17.458000Z',
                                  end_time: '2021-10-04T05:38:50.133000Z',
                                  distinct_id: 'Nr5jM7FCbz1XaBmFBmsny4NrDmU9y9lOx1Cb3c2DAAw',
                                  email: 'test@posthog.com',
                                  click_count: 45,
                                  keypress_count: 0,
                                  snapshot_source: 'web',
                                  person: {
                                      id: '12345',
                                      name: 'Ms Testy McTesterson',
                                      distinct_ids: ['Nr5jM7FCbz1XaBmFBmsny4NrDmU9y9lOx1Cb3c2DAAw'],
                                      properties: {
                                          $os: 'Linux',
                                          $browser: 'Microsoft Edge',
                                          $referrer: '$direct',
                                          $initial_os: 'Linux',
                                          $geoip_country_name: 'Nigeria',
                                          $geoip_country_code: 'NG',
                                          email: 'test@posthog.com',
                                      },
                                  },
                              },
                          ]
                        : [404, {}]
                },
                'api/projects/:team/notebooks': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
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
export const NotFound: Story = {
    parameters: {
        testOptions: { waitForLoadersToDisappear: false, waitForSelector: '[data-attr="not-found-recording"]' },
    },
}

export const PastTTL: Story = {
    parameters: {
        pageUrl: urls.replaySingle('past-ttl'),
        testOptions: {
            waitForLoadersToDisappear: false,
            waitForSelector: '[data-attr="session-recording-player-past-ttl"]',
        },
    },
}
