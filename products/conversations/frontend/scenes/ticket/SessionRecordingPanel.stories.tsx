import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { HttpResponse } from 'msw'
import { useEffect, useRef } from 'react'

import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { ReplayObservationApi } from 'products/replay_vision/frontend/generated/api.schemas'

import { SessionRecordingPanel } from './SessionRecordingPanel'

// The ticket scene gives this panel the sidebar column next to the chat: about 300px when the
// chat panel is wide, up to about 600px on a large window. Both widths get a story.

const RECORDING_ID = recordingMetaJson.id
const DISTINCT_ID = recordingMetaJson.distinct_id

const SUMMARY: ReplayObservationApi = {
    id: '019f9582-93e7-77c1-8912-4f541d70cb13',
    scanner_id: 'inline-summary',
    scanner_origin: 'inline',
    session_id: RECORDING_ID,
    status: 'succeeded',
    error_reason: '',
    workflow_id: '',
    scanner_snapshot: { name: 'Quick summary', scanner_type: 'summarizer' },
    scanner_result: {
        model_output: {
            title: 'Checkout failed after a coupon code was applied',
            summary:
                'The user added two items to the cart and opened checkout. They entered a coupon code, which was accepted, then pressed Pay. The page showed a validation error on the card field twice before they gave up and opened the support widget.',
        },
        signals_count: 0,
    },
    triggered_by: 'on_demand',
    triggered_by_user: null,
    backfill_id: null,
} as ReplayObservationApi

// Summarizing needs scanner editor access, which the storybook app context does not grant by default.
const grantScannerAccess: Decorator = function GrantScannerAccess(Story): JSX.Element {
    const appContext = (window as any).POSTHOG_APP_CONTEXT
    const original = useRef<{ value: unknown }>()
    if (appContext && !original.current) {
        original.current = { value: appContext.resource_access_control }
        appContext.resource_access_control = {
            ...appContext.resource_access_control,
            [AccessControlResourceType.ReplayScanner]: AccessControlLevel.Editor,
            [AccessControlResourceType.SessionRecording]: AccessControlLevel.Editor,
        }
    }
    useEffect(
        () => () => {
            if (appContext && original.current) {
                appContext.resource_access_control = original.current.value
            }
        },
        [appContext]
    )
    return <Story />
}

function visionMocks(observations: ReplayObservationApi[]): Decorator {
    return mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
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
                                start_timestamp: '2023-08-11T12:03:36.097000Z',
                                end_timestamp: '2023-08-11T12:04:52.268000Z',
                                blob_key: '0',
                            },
                        ],
                    },
                ]
            },
            'api/projects/:team/notebooks': { count: 0, next: null, previous: null, results: [] },
            '/api/projects/:team_id/vision/observations/': { count: observations.length, results: observations },
            '/api/projects/:team_id/vision/scanners/': { count: 0, next: null, previous: null, results: [] },
            '/api/projects/:team_id/vision/quota/': {
                credit_limit: null,
                credits_used: 0,
                remaining: null,
                exhausted: false,
                period_start: '2023-08-01T00:00:00Z',
                period_end: '2023-09-01T00:00:00Z',
                projected_monthly_credits: 0,
                scanners_monthly_credits: 0,
                backfills_committed_credits: 0,
                free_monthly_credits: 0,
            },
        },
        post: {
            '/api/environments/:team_id/query/:kind': () => [200, { results: [] }],
        },
    })
}

const meta: Meta<typeof SessionRecordingPanel> = {
    title: 'Scenes-App/Support/SessionRecordingPanel',
    component: SessionRecordingPanel,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2023-08-11',
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [
        grantScannerAccess,
        // The app shell mounts this modal globally; "Expand" opens the recording in it
        (Story) => (
            <>
                <Story />
                <SessionPlayerModal />
            </>
        ),
        visionMocks([]),
    ],
}
export default meta

type Story = StoryObj<typeof SessionRecordingPanel>

function Sidebar({ width, children }: { width: number; children: React.ReactNode }): JSX.Element {
    // eslint-disable-next-line react/forbid-dom-props
    return <div style={{ width }}>{children}</div>
}

const withRecording = { sessionContext: { session_replay_url: `/replay/${RECORDING_ID}` }, distinctId: DISTINCT_ID }

export const NarrowSidebar: Story = {
    render: () => (
        <Sidebar width={320}>
            <SessionRecordingPanel {...withRecording} />
        </Sidebar>
    ),
}

export const WideSidebar: Story = {
    render: () => (
        <Sidebar width={560}>
            <SessionRecordingPanel {...withRecording} />
        </Sidebar>
    ),
}

export const Summarized: Story = {
    decorators: [visionMocks([SUMMARY])],
    render: () => (
        <Sidebar width={320}>
            <SessionRecordingPanel {...withRecording} />
        </Sidebar>
    ),
}

export const NoRecording: Story = {
    render: () => (
        <Sidebar width={320}>
            <SessionRecordingPanel sessionContext={{}} distinctId={DISTINCT_ID} />
        </Sidebar>
    ),
}
