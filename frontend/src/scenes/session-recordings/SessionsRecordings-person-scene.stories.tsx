import { Meta, StoryFn } from '@storybook/react'
import { combineUrl, router } from 'kea-router'

import { App } from 'scenes/App'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

const personUUID = '741cc6c0-7c48-55f2-9b58-1b648a381c9e'

const threeRecordings = [
    {
        id: 'rec-001-apple',
        distinct_id: 'person-distinct-id-001',
        viewed: false,
        viewers: [],
        recording_duration: 351,
        active_seconds: 24,
        inactive_seconds: 326,
        start_time: '2023-07-04T22:53:48.554000Z',
        end_time: '2023-07-04T22:59:39.681000Z',
        click_count: 7,
        keypress_count: 12,
        mouse_activity_count: 72,
        console_log_count: 2,
        console_warn_count: 0,
        console_error_count: 7,
        start_url: 'https://us.posthog.com/signup/test-page-1',
        person: {
            id: 99999999999,
            name: 'test@posthog.com',
            distinct_ids: ['person-distinct-id-001'],
            properties: { $os: 'Mac OS X', email: 'test@posthog.com' },
            created_at: '2023-07-04T22:53:38.784000Z',
            uuid: 'person-uuid-001',
        },
        snapshot_source: 'web',
        ongoing: false,
        activity_score: 11.62,
    },
    {
        id: 'rec-002-banana',
        distinct_id: 'person-distinct-id-001',
        viewed: true,
        viewers: ['user-123'],
        recording_duration: 542,
        active_seconds: 120,
        inactive_seconds: 422,
        start_time: '2023-07-04T21:00:00.000000Z',
        end_time: '2023-07-04T21:09:02.000000Z',
        click_count: 45,
        keypress_count: 23,
        mouse_activity_count: 156,
        console_log_count: 5,
        console_warn_count: 1,
        console_error_count: 2,
        start_url: 'https://us.posthog.com/dashboard',
        person: {
            id: 99999999999,
            name: 'test@posthog.com',
            distinct_ids: ['person-distinct-id-001'],
            properties: { $os: 'Mac OS X', email: 'test@posthog.com' },
            created_at: '2023-07-04T22:53:38.784000Z',
            uuid: 'person-uuid-001',
        },
        snapshot_source: 'web',
        ongoing: false,
        activity_score: 25.5,
    },
    {
        id: 'rec-003-cherry',
        distinct_id: 'person-distinct-id-001',
        viewed: false,
        viewers: [],
        recording_duration: 128,
        active_seconds: 80,
        inactive_seconds: 48,
        start_time: '2023-07-04T20:00:00.000000Z',
        end_time: '2023-07-04T20:02:08.000000Z',
        click_count: 18,
        keypress_count: 5,
        mouse_activity_count: 42,
        console_log_count: 0,
        console_warn_count: 0,
        console_error_count: 0,
        start_url: 'https://us.posthog.com/settings',
        person: {
            id: 99999999999,
            name: 'test@posthog.com',
            distinct_ids: ['person-distinct-id-001'],
            properties: { $os: 'Mac OS X', email: 'test@posthog.com' },
            created_at: '2023-07-04T22:53:38.784000Z',
            uuid: 'person-uuid-001',
        },
        snapshot_source: 'web',
        ongoing: false,
        activity_score: 8.2,
    },
]

const personQueryResponse = {
    columns: ['id', 'distinct_ids', 'properties', 'is_identified', 'created_at'],
    results: [
        [
            'b4957134-eae2-58b2-ab91-012b73df0b91',
            ['person-distinct-id-001'],
            '{"$os": "Mac OS X", "email": "test@posthog.com"}',
            1,
            '2023-07-04T22:53:38.784000Z',
        ],
    ],
    hasMore: false,
    is_cached: true,
    cache_key: 'test-datatable',
    calculation_trigger: null,
    error: '',
    query_status: null,
}

const meta: Meta = {
    title: 'Replay/Scenes/Person',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04',
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/': (req) => {
                    const query = (req.body as any)?.query
                    if (query?.kind === 'HogQLQuery' && query?.values?.id === personUUID) {
                        return [200, personQueryResponse]
                    }
                    return [200, { results: [] }]
                },
            },
        }),
    ],
}
export default meta

export const PersonRecordingTabEmpty: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/session_recordings': () => [200, { results: [] }],
        },
        post: {
            '/api/environments/:team_id/query/': (req) => {
                const query = (req.body as any)?.query
                if (query?.kind === 'HogQLQuery' && query?.values?.id === personUUID) {
                    return [200, personQueryResponse]
                }
                return [200, { results: [] }]
            },
        },
    })

    router.actions.push(combineUrl(urls.personByUUID(personUUID), {}, { activeTab: 'sessionRecordings' }).url)

    return <App />
}

export const PersonRecordingTabMultipleAndNotFound: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/session_recordings/': () => [200, { results: threeRecordings }],
        },
    })

    router.actions.push(combineUrl(urls.personByUUID(personUUID), {}, { activeTab: 'sessionRecordings' }).url)

    return <App />
}

export const PersonRecordingTabMultipleAndFound: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/session_recordings/': () => [200, { results: threeRecordings }],
            '/api/environments/:team_id/session_recordings/:id': () => [
                200,
                { ...recordingMetaJson, id: 'rec-002-banana' },
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
    })

    router.actions.push(
        combineUrl(
            urls.personByUUID(personUUID),
            { sessionRecordingId: 'rec-002-banana', pause: true, inspectorSideBar: true, tab: 'inspector', t: 2 },
            { activeTab: 'sessionRecordings' }
        ).url
    )

    return <App />
}
PersonRecordingTabMultipleAndFound.parameters = {
    testOptions: {
        waitForSelector: '.PlayerFrame__content .replayer-wrapper iframe',
    },
}
PersonRecordingTabMultipleAndFound.tags = ['test-skip']

export const PersonRecordingTabWide: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/session_recordings/': () => [200, { results: threeRecordings }],
            '/api/environments/:team_id/session_recordings/:id': () => [
                200,
                { ...recordingMetaJson, id: 'rec-001-apple' },
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
    })

    router.actions.push(
        combineUrl(
            urls.personByUUID(personUUID),
            { sessionRecordingId: 'rec-001-apple', pause: true, inspectorSideBar: true, tab: 'inspector', t: 2 },
            { activeTab: 'sessionRecordings' }
        ).url
    )

    return <App />
}
PersonRecordingTabWide.parameters = {
    testOptions: {
        viewport: { width: 1300, height: 720 },
        waitForSelector: '.PlayerFrame__content .replayer-wrapper iframe',
    },
}
PersonRecordingTabWide.tags = ['test-skip']

export const PersonRecordingTabNarrow: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/session_recordings/': () => [200, { results: threeRecordings }],
            '/api/environments/:team_id/session_recordings/:id': () => [
                200,
                { ...recordingMetaJson, id: 'rec-001-apple' },
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
    })

    router.actions.push(
        combineUrl(
            urls.personByUUID(personUUID),
            { sessionRecordingId: 'rec-001-apple', pause: true, inspectorSideBar: true, tab: 'inspector', t: 2 },
            { activeTab: 'sessionRecordings' }
        ).url
    )

    return <App />
}
PersonRecordingTabNarrow.parameters = {
    testOptions: {
        viewport: { width: 568, height: 1024 },
        waitForSelector: '.PlayerFrame__content .replayer-wrapper iframe',
    },
}
PersonRecordingTabNarrow.tags = ['test-skip']

export const PersonEventsTabWithModal: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/session_recordings/': () => [200, { results: threeRecordings }],
            '/api/environments/:team_id/session_recordings/:id': () => [
                200,
                { ...recordingMetaJson, id: 'rec-001-apple' },
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
    })

    router.actions.push(
        combineUrl(
            urls.personByUUID(personUUID),
            { pause: true, inspectorSideBar: true, tab: 'inspector', t: 2 },
            { activeTab: 'events', sessionRecordingId: 'rec-001-apple' }
        ).url
    )

    return <App />
}
PersonEventsTabWithModal.parameters = {
    testOptions: {
        waitForSelector: '.PlayerFrame__content .replayer-wrapper iframe',
    },
}
PersonEventsTabWithModal.tags = ['test-skip']
