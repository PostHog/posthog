import { Meta, StoryFn } from '@storybook/react'
import { combineUrl, router } from 'kea-router'

import { App } from 'scenes/App'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { urls } from 'scenes/urls'

import { FEATURE_FLAGS } from '~/lib/constants'
import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { ActivityTab } from '~/types'

import eventsQuery from '../activity/explore/__mocks__/eventsQuery.json'

const meta: Meta = {
    component: App,
    title: 'Replay/Scenes/Activity Modal',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28',
        featureFlags: [FEATURE_FLAGS.SESSIONS_EXPLORER],
        testOptions: {
            loaderTimeout: 15000,
        },
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query': eventsQuery,
            },
        }),
    ],
}
export default meta

export const EventExplorerWithModal: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/session_recordings/:id/': () => [
                200,
                { ...recordingMetaJson, id: 'modal-recording-001' },
            ],
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
                                start_timestamp: '2023-08-11T12:03:36.097000Z',
                                end_timestamp: '2023-08-11T12:04:52.268000Z',
                                blob_key: '0',
                            },
                        ],
                    },
                ]
            },
        },
        post: {
            '/api/environments/:team_id/query': eventsQuery,
        },
    })

    router.actions.push(
        combineUrl(
            urls.activity(ActivityTab.ExploreEvents),
            { pause: true, inspectorSideBar: true, tab: 'inspector', t: 4 },
            { sessionRecordingId: 'modal-recording-001' }
        ).url
    )

    return <App />
}
EventExplorerWithModal.parameters = {
    testOptions: {
        waitForSelector: '.PlayerFrame__content .replayer-wrapper iframe',
    },
}
EventExplorerWithModal.tags = ['test-skip']

export const EventExplorerWithModalNotFound: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/session_recordings/:id': () => [404, { detail: 'Not found.' }],
            '/api/environments/:team_id/session_recordings/:id/snapshots': () => [404, { detail: 'Not found.' }],
        },
        post: {
            '/api/environments/:team_id/query': eventsQuery,
        },
    })

    router.actions.push(
        combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { sessionRecordingId: 'non-existent-recording' }).url
    )

    return <App />
}
