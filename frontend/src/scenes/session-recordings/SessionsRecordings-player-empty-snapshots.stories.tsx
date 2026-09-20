import { Meta, StoryObj } from '@storybook/react'
import { HttpResponse } from 'msw'

import { App } from 'scenes/App'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { recordings } from './__mocks__/recordings'

const meta: Meta = {
    component: App,
    title: 'Replay/Tabs/Home/Empty snapshots',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-06-01',
        pageUrl: urls.replay(),
    },
    decorators: [
        // Metadata says the recording exists, but every source comes back with no snapshots
        mswDecorator({
            get: {
                '/stats': () => [200, { users_on_product: 42, active_recordings: 7 }],
                '/api/environments/:team_id/session_recordings': ({ request }) => [
                    200,
                    { has_next: false, results: recordings, version: new URL(request.url).searchParams.get('version') },
                ],
                '/api/environments/:team_id/session_recordings/:id': () => [200, recordingMetaJson],
                '/api/environments/:team_id/session_recordings/:id/snapshots': ({ request }) => {
                    if (new URL(request.url).searchParams.get('source') === 'blob_v2') {
                        return new HttpResponse('')
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
            },
            post: {
                '/api/environments/:team_id/query/:kind': recordingEventsJson,
                '/api/environments/:team_id/session_recordings/:id/capture_diagnostics': { properties: null },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const EmptySnapshots: Story = {
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}
