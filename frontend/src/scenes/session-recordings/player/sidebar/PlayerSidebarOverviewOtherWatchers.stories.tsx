import { Meta } from '@storybook/react'
import { BindLogic } from 'kea'

import { mswDecorator } from '~/mocks/browser'

import { sessionRecordingDataCoordinatorLogic } from '../sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarOverviewOtherWatchers } from './PlayerSidebarOverviewOtherWatchers'

const meta: Meta<typeof PlayerSidebarOverviewOtherWatchers> = {
    title: 'Replay/Overview Tab/Other Watchers',
    component: PlayerSidebarOverviewOtherWatchers,
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    tags: ['autodocs'],
}
export default meta

// Wrapper component that provides the required logic props
function MockedPlayerSidebarOverviewOtherWatchers({ startExpanded = false }: { startExpanded?: boolean }): JSX.Element {
    return (
        <BindLogic
            logic={sessionRecordingDataCoordinatorLogic}
            props={{
                sessionRecordingId: 'test-session-id',
                playerKey: 'story-template',
            }}
        >
            <BindLogic
                logic={sessionRecordingPlayerLogic}
                props={{
                    sessionRecordingId: 'test-session-id',
                    playerKey: 'story-template',
                }}
            >
                <PlayerSidebarOverviewOtherWatchers startExpanded={startExpanded} />
            </BindLogic>
        </BindLogic>
    )
}

export function Default(): JSX.Element {
    return <MockedPlayerSidebarOverviewOtherWatchers />
}
Default.decorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings/:id': {
                id: 'test-session-id',
                session_id: 'test-session-id',
                distinct_id: 'test-user',
                start_time: '2024-01-01T00:00:00Z',
                end_time: '2024-01-01T00:01:00Z',
                duration: 60,
                click_count: 5,
                keypress_count: 10,
                mouse_activity_count: 15,
                console_log_count: 0,
                console_warn_count: 0,
                console_error_count: 0,
                size: 1024,
                events_count: 20,
                recording_duration: 60,
                view_count: 1,
                viewers: ['alice@posthog.com', 'bob@posthog.com', 'charlie@posthog.com', 'diana@posthog.com'],
                person: {
                    id: 1,
                    uuid: 'test-uuid',
                    distinct_id: 'test-user',
                    properties: {
                        email: 'current@posthog.com',
                    },
                },
            },
        },
    }),
]

export function Expanded(): JSX.Element {
    return <MockedPlayerSidebarOverviewOtherWatchers startExpanded={true} />
}
Expanded.decorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings/:id': {
                id: 'test-session-id',
                session_id: 'test-session-id',
                distinct_id: 'test-user',
                start_time: '2024-01-01T00:00:00Z',
                end_time: '2024-01-01T00:01:00Z',
                duration: 60,
                click_count: 5,
                keypress_count: 10,
                mouse_activity_count: 15,
                console_log_count: 0,
                console_warn_count: 0,
                console_error_count: 0,
                size: 1024,
                events_count: 20,
                recording_duration: 60,
                view_count: 1,
                viewers: ['alice@posthog.com', 'bob@posthog.com', 'charlie@posthog.com', 'diana@posthog.com'],
                person: {
                    id: 1,
                    uuid: 'test-uuid',
                    distinct_id: 'test-user',
                    properties: {
                        email: 'current@posthog.com',
                    },
                },
            },
        },
    }),
]

export function WithMultipleViewers(): JSX.Element {
    return <MockedPlayerSidebarOverviewOtherWatchers startExpanded={true} />
}
WithMultipleViewers.decorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings/:id': {
                id: 'test-session-id',
                session_id: 'test-session-id',
                distinct_id: 'test-user',
                start_time: '2024-01-01T00:00:00Z',
                end_time: '2024-01-01T00:01:00Z',
                duration: 60,
                click_count: 5,
                keypress_count: 10,
                mouse_activity_count: 15,
                console_log_count: 0,
                console_warn_count: 0,
                console_error_count: 0,
                size: 1024,
                events_count: 20,
                recording_duration: 60,
                view_count: 1,
                viewers: [
                    'alice@posthog.com',
                    'bob@posthog.com',
                    'charlie@posthog.com',
                    'diana@posthog.com',
                    'eve@posthog.com',
                    'frank@posthog.com',
                ],
                person: {
                    id: 1,
                    uuid: 'test-uuid',
                    distinct_id: 'test-user',
                    properties: {
                        email: 'current@posthog.com',
                    },
                },
            },
        },
    }),
]

export function NoOtherWatchers(): JSX.Element {
    return <MockedPlayerSidebarOverviewOtherWatchers />
}
NoOtherWatchers.decorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings/:id': {
                id: 'test-session-id',
                session_id: 'test-session-id',
                distinct_id: 'test-user',
                start_time: '2024-01-01T00:00:00Z',
                end_time: '2024-01-01T00:01:00Z',
                duration: 60,
                click_count: 5,
                keypress_count: 10,
                mouse_activity_count: 15,
                console_log_count: 0,
                console_warn_count: 0,
                console_error_count: 0,
                size: 1024,
                events_count: 20,
                recording_duration: 60,
                view_count: 1,
                viewers: [], // No other viewers
                person: {
                    id: 1,
                    uuid: 'test-uuid',
                    distinct_id: 'test-user',
                    properties: {
                        email: 'current@posthog.com',
                    },
                },
            },
        },
    }),
]
