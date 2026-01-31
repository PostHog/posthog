import { Meta, StoryFn } from '@storybook/react'
import { BindLogic } from 'kea'

import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { mswDecorator } from '~/mocks/browser'

import { PlayerMetaBar } from './PlayerMetaBar'

const meta: Meta = {
    title: 'Replay/Player/Meta',
    component: PlayerMetaBar,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-01',
        testOptions: {
            waitForSelector: '[data-attr="session-recording-speed-select"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/notebooks/recording_comments': { results: [] },
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
                                    start_timestamp: '2023-05-01T14:46:20.877000Z',
                                    end_timestamp: '2023-05-01T14:46:32.745000Z',
                                    blob_key: '0',
                                },
                            ],
                        },
                    ]
                },
                '/api/environments/:team_id/session_recordings/:id': (req, res, ctx) => {
                    if (req.params.id === 'low_ttl') {
                        return res(ctx.json({ ...recordingMetaJson, recording_ttl: 3 }))
                    }
                    return res(ctx.json(recordingMetaJson))
                },
            },
            post: {
                '/api/environments/:team_id/query': (req, res, ctx) => {
                    const body = req.body as Record<string, any>
                    if (body.query.kind === 'HogQLQuery') {
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
                                        recordingMetaJson.id,
                                        'GB',
                                        'Chrome',
                                        'Desktop',
                                        'Mac OS X',
                                        '',
                                        'hedgehog.io',
                                        'London',
                                        'Hogington',
                                        'https://hedgehog.io/entry-page',
                                    ],
                                ],
                            })
                        )
                    }
                    if (body.query.kind === 'EventsQuery') {
                        return res(ctx.json(recordingEventsJson))
                    }
                    return res(ctx.json({ results: [] }))
                },
            },
        }),
    ],
}

export default meta

interface MetaBarStoryProps {
    width: number
    sessionId?: string
    withSidebar?: boolean
}

const MetaBarTemplate: StoryFn<MetaBarStoryProps> = ({
    width,
    sessionId = '12345',
    withSidebar = true,
}: MetaBarStoryProps) => {
    return (
        <div style={{ width: `${width}px` }} className="bg-surface-primary overflow-hidden">
            <BindLogic
                logic={sessionRecordingPlayerLogic}
                props={{
                    playerKey: 'storybook',
                    sessionRecordingId: sessionId,
                    withSidebar,
                }}
            >
                <PlayerMetaBar />
            </BindLogic>
        </div>
    )
}

export const Default = MetaBarTemplate.bind({})
Default.args = { width: 800 }

export const WithoutSidebar = MetaBarTemplate.bind({})
WithoutSidebar.args = { width: 800, withSidebar: false }

export const Narrow = MetaBarTemplate.bind({})
Narrow.args = { width: 400 }

export const LowTTL = MetaBarTemplate.bind({})
LowTTL.args = { width: 800, sessionId: 'low_ttl' }

export const LowTTLNarrow = MetaBarTemplate.bind({})
LowTTLNarrow.args = { width: 400, sessionId: 'low_ttl' }
