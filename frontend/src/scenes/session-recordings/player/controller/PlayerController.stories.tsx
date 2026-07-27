import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { HttpResponse } from 'msw'

import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import {
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { mswDecorator } from '~/mocks/browser'

import { PlayerController } from './PlayerController'

interface ControllerStoryProps {
    width: number
    mode?: SessionRecordingPlayerMode
    showPlayNext?: boolean
}

type Story = StoryObj<ControllerStoryProps>
const meta: Meta<ControllerStoryProps> = {
    title: 'Replay/Player/Controller',
    component: PlayerController,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-01',
        testOptions: {
            waitForSelector: '.PlayerSeekbar__slider',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/notebooks/recording_comments': { results: [] },
                '/api/environments/:team_id/session_recordings/:id/snapshots': ({ request }) => {
                    if (new URL(request.url).searchParams.get('source') === 'blob_v2') {
                        return new HttpResponse(snapshotsAsJSONLines())
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
                '/api/environments/:team_id/session_recordings/:id': () => [200, recordingMetaJson],
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
    render: ({ width, mode, showPlayNext = false }: ControllerStoryProps) => {
        return (
            <div style={{ width: `${width}px` }} className="relative bg-surface-primary p-2 overflow-hidden min-h-20">
                <BindLogic
                    logic={sessionRecordingPlayerLogic}
                    props={{
                        playerKey: 'storybook',
                        sessionRecordingId: '12345',
                        mode: mode ?? SessionRecordingPlayerMode.Standard,
                        playNextRecording: showPlayNext ? () => {} : undefined,
                    }}
                >
                    <PlayerController />
                </BindLogic>
            </div>
        )
    },
}

export default meta

export const Default: Story = {
    args: { width: 800 },
}

export const Narrow: Story = {
    args: { width: 400 },
}

export const Wide: Story = {
    args: { width: 1200 },
}

export const NotebookMode: Story = {
    args: { width: 600, mode: SessionRecordingPlayerMode.Notebook },
}

export const WithPlayNext: Story = {
    args: { width: 800, showPlayNext: true },
}
