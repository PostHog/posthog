import type { Meta, StoryObj } from '@storybook/react'
import { HttpResponse } from 'msw'

import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { lateFullSnapshotAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'

import { mswDecorator } from '~/mocks/browser'

// the first snapshot lands at the recording start, but the full snapshot only arrives 60s later
const LATE_SNAPSHOT_BASE = 1682952380877 // 2023-05-01T14:46:20.877Z
const LATE_BY_MS = 60000

const lateRecordingMocks = (recordingDurationSeconds: number): Parameters<typeof mswDecorator>[0] => ({
    get: {
        '/api/projects/:team_id/notebooks/recording_comments': { results: [] },
        '/api/environments/:team_id/session_recordings/:id/snapshots': ({ request }) => {
            if (new URL(request.url).searchParams.get('source') === 'blob_v2') {
                return new HttpResponse(lateFullSnapshotAsJSONLines(LATE_SNAPSHOT_BASE, LATE_BY_MS))
            }
            return [
                200,
                {
                    sources: [
                        {
                            source: 'blob_v2',
                            start_timestamp: new Date(LATE_SNAPSHOT_BASE).toISOString(),
                            end_timestamp: new Date(LATE_SNAPSHOT_BASE + LATE_BY_MS + 5000).toISOString(),
                            blob_key: '0',
                        },
                    ],
                },
            ]
        },
        '/api/environments/:team_id/session_recordings/:id': () => [
            200,
            {
                ...recordingMetaJson,
                recording_duration: recordingDurationSeconds,
                start_time: new Date(LATE_SNAPSHOT_BASE).toISOString(),
                end_time: new Date(LATE_SNAPSHOT_BASE + recordingDurationSeconds * 1000).toISOString(),
            },
        ],
    },
    post: {
        '/api/environments/:team_id/query/:kind': async ({ request }) => {
            const body = (await request.json()) as Record<string, any>
            if (body.query.kind === 'EventsQuery') {
                return [200, recordingEventsJson]
            }
            return [200, { results: [] }]
        },
    },
})

type Story = StoryObj<typeof SessionRecordingPlayer>
const meta: Meta<typeof SessionRecordingPlayer> = {
    title: 'Replay/Player/LateFullSnapshot',
    component: SessionRecordingPlayer,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-01',
    },
    render: () => (
        <div className="h-120 w-full">
            <SessionRecordingPlayer sessionRecordingId="12345" playerKey="storybook" withSidebar={false} />
        </div>
    ),
}

export default meta

// playback recovers 60s in, so the banner reports the activity that stretch holds
export const PartOfTheRecordingIsLost: Story = {
    decorators: [mswDecorator(lateRecordingMocks(65))],
    parameters: { testOptions: { waitForSelector: '.LemonBanner' } },
}

// the full snapshot lands after the recording ends, so there is no frame to play and the takeover
// replaces the player instead of a banner that cancels itself
export const TheWholeRecordingIsLost: Story = {
    decorators: [mswDecorator(lateRecordingMocks(30))],
    parameters: { testOptions: { waitForSelector: '[data-attr="player-error-overlay"]' } },
}
