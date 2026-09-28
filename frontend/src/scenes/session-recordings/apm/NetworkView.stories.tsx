import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic, useActions } from 'kea'
import { EventType } from 'posthog-js/rrweb-types'
import { useEffect } from 'react'

import { NetworkView } from 'scenes/session-recordings/apm/NetworkView'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { mswDecorator } from '~/mocks/browser'
import { RecordingSnapshot } from '~/types'

type Story = StoryObj<{}>

const SESSION_START = 1731662368625
const WINDOW_ID = 1

const navigationRequest = {
    name: 'https://example.com/dashboard',
    entryType: 'navigation',
    initiatorType: 'navigation',
    startTime: 0,
    domainLookupStart: 0,
    domainLookupEnd: 45,
    connectStart: 45,
    connectEnd: 120,
    requestStart: 120,
    responseStart: 350,
    responseEnd: 1200,
    loadEventEnd: 2500,
    domInteractive: 900,
    responseStatus: 200,
}

const resourceRequests = [
    {
        name: 'https://example.com/static/main.js',
        entryType: 'resource',
        initiatorType: 'script',
        startTime: 150,
        responseEnd: 800,
        responseStatus: 200,
    },
    {
        name: 'https://example.com/static/styles.css',
        entryType: 'resource',
        initiatorType: 'css',
        startTime: 160,
        responseEnd: 450,
        responseStatus: 200,
    },
    {
        name: 'https://example.com/api/insights?short_id=abc123',
        entryType: 'resource',
        initiatorType: 'fetch',
        startTime: 900,
        requestStart: 910,
        responseStart: 1600,
        responseEnd: 1800,
        responseStatus: 200,
    },
    {
        name: 'https://example.com/api/recordings?limit=20',
        entryType: 'resource',
        initiatorType: 'xmlhttprequest',
        startTime: 950,
        responseEnd: 1600,
        responseStatus: 404,
    },
]

function networkSnapshots(requests: Record<string, unknown>[]): RecordingSnapshot[] {
    return [
        {
            windowId: WINDOW_ID,
            type: EventType.Meta,
            data: { href: 'https://example.com/dashboard', width: 1200, height: 800 },
            timestamp: SESSION_START,
        },
        ...requests.map(
            (request, index): RecordingSnapshot => ({
                windowId: WINDOW_ID,
                type: EventType.Plugin,
                data: { plugin: 'rrweb/network@1', payload: { requests: [request] } },
                timestamp: SESSION_START + index * 100,
            })
        ),
    ]
}

function NetworkViewStory({ snapshots }: { snapshots: RecordingSnapshot[] }): JSX.Element {
    const playerProps = { sessionRecordingId: '12345', playerKey: 'story-template' }
    const { loadRecordingFromFile } = useActions(sessionRecordingDataCoordinatorLogic(playerProps))

    useEffect(() => {
        loadRecordingFromFile({ id: '12345', person: undefined, snapshots })
    }, [loadRecordingFromFile, snapshots])

    return (
        <div className="flex flex-col min-w-96 min-h-120">
            <BindLogic logic={sessionRecordingPlayerLogic} props={playerProps}>
                <NetworkView />
            </BindLogic>
        </div>
    )
}

const meta: Meta = {
    title: 'Scenes/Session Recordings/NetworkView',
    component: NetworkView,
    parameters: {
        layout: 'padded',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/session_recordings/:id/snapshots': { sources: [] },
            },
            post: {
                '/api/environments/:team_id/query/:kind': () => [200, { results: [] }],
            },
            patch: {
                '/api/environments/:team_id/session_recordings/:id': () => [200, {}],
            },
        }),
    ],
}
export default meta

export const Default: Story = {
    render: () => <NetworkViewStory snapshots={networkSnapshots([navigationRequest, ...resourceRequests])} />,
}

// a recording that starts after the document loaded captures requests but no navigation entry
export const RecordingStartedMidPage: Story = {
    render: () => <NetworkViewStory snapshots={networkSnapshots(resourceRequests)} />,
}
