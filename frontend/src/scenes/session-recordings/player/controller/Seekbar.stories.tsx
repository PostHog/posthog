import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { HttpResponse } from 'msw'

import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { lateFullSnapshotAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import {
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { mswDecorator } from '~/mocks/browser'

import { PlayerController } from './PlayerController'

// first snapshot at the recording start, but the full snapshot only arrives 60s later
const LATE_SNAPSHOT_BASE = 1682952380877 // 2023-05-01T14:46:20.877Z

const lateRecordingMeta = {
    ...recordingMetaJson,
    recording_duration: 65,
    start_time: '2023-05-01T14:46:20.877000Z',
    end_time: '2023-05-01T14:47:25.877000Z',
}

type Story = StoryObj<{ width: number }>
const meta: Meta<{ width: number }> = {
    title: 'Replay/Player/Seekbar',
    component: PlayerController,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-01',
        testOptions: {
            waitForSelector: '.PlayerSeekbar__unplayable',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/notebooks/recording_comments': { results: [] },
                '/api/environments/:team_id/session_recordings/:id/snapshots': ({ request }) => {
                    if (new URL(request.url).searchParams.get('source') === 'blob_v2') {
                        return new HttpResponse(lateFullSnapshotAsJSONLines(LATE_SNAPSHOT_BASE, 60000))
                    }
                    return [
                        200,
                        {
                            sources: [
                                {
                                    source: 'blob_v2',
                                    start_timestamp: lateRecordingMeta.start_time,
                                    end_timestamp: lateRecordingMeta.end_time,
                                    blob_key: '0',
                                },
                            ],
                        },
                    ]
                },
                '/api/environments/:team_id/session_recordings/:id': () => [200, lateRecordingMeta],
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
        }),
    ],
    render: ({ width }) => {
        return (
            <div style={{ width: `${width}px` }} className="relative bg-surface-primary p-2 overflow-hidden min-h-20">
                <BindLogic
                    logic={sessionRecordingPlayerLogic}
                    props={{
                        playerKey: 'storybook',
                        sessionRecordingId: '12345',
                        mode: SessionRecordingPlayerMode.Standard,
                    }}
                >
                    <PlayerController />
                </BindLogic>
            </div>
        )
    },
}

export default meta

// the leading section before the late full snapshot is hatched as unplayable on the scrubber
export const LateFullSnapshot: Story = {
    args: { width: 800 },
}
