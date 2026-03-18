import { Meta, StoryFn } from '@storybook/react'
import { combineUrl, router } from 'kea-router'

import { App } from 'scenes/App'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

const groupTypeIndex = 0
const groupKey = 'test-company-123'

const threeRecordings = [
    {
        id: 'group-rec-001',
        distinct_id: 'user-in-group-001',
        viewed: false,
        viewers: [],
        recording_duration: 420,
        active_seconds: 120,
        inactive_seconds: 300,
        start_time: '2023-07-04T10:00:00.000000Z',
        end_time: '2023-07-04T10:07:00.000000Z',
        click_count: 25,
        keypress_count: 15,
        mouse_activity_count: 80,
        console_log_count: 3,
        console_warn_count: 0,
        console_error_count: 1,
        start_url: 'https://app.example.com/dashboard',
        person: {
            id: 1001,
            name: 'alice@example.com',
            distinct_ids: ['user-in-group-001'],
            properties: { $os: 'Windows', email: 'alice@example.com' },
            created_at: '2023-07-01T00:00:00.000000Z',
            uuid: 'person-uuid-001',
        },
        snapshot_source: 'web',
        ongoing: false,
        activity_score: 15.5,
    },
    {
        id: 'group-rec-002',
        distinct_id: 'user-in-group-002',
        viewed: true,
        viewers: ['admin-user'],
        recording_duration: 180,
        active_seconds: 90,
        inactive_seconds: 90,
        start_time: '2023-07-04T09:00:00.000000Z',
        end_time: '2023-07-04T09:03:00.000000Z',
        click_count: 12,
        keypress_count: 8,
        mouse_activity_count: 45,
        console_log_count: 1,
        console_warn_count: 0,
        console_error_count: 0,
        start_url: 'https://app.example.com/settings',
        person: {
            id: 1002,
            name: 'bob@example.com',
            distinct_ids: ['user-in-group-002'],
            properties: { $os: 'Mac OS X', email: 'bob@example.com' },
            created_at: '2023-07-01T00:00:00.000000Z',
            uuid: 'person-uuid-002',
        },
        snapshot_source: 'web',
        ongoing: false,
        activity_score: 22.1,
    },
    {
        id: 'group-rec-003',
        distinct_id: 'user-in-group-003',
        viewed: false,
        viewers: [],
        recording_duration: 600,
        active_seconds: 200,
        inactive_seconds: 400,
        start_time: '2023-07-04T08:00:00.000000Z',
        end_time: '2023-07-04T08:10:00.000000Z',
        click_count: 55,
        keypress_count: 30,
        mouse_activity_count: 120,
        console_log_count: 8,
        console_warn_count: 2,
        console_error_count: 3,
        start_url: 'https://app.example.com/reports',
        person: {
            id: 1003,
            name: 'charlie@example.com',
            distinct_ids: ['user-in-group-003'],
            properties: { $os: 'Linux', email: 'charlie@example.com' },
            created_at: '2023-07-01T00:00:00.000000Z',
            uuid: 'person-uuid-003',
        },
        snapshot_source: 'web',
        ongoing: false,
        activity_score: 35.8,
    },
]

const groupData = {
    id: groupKey,
    group_type_index: groupTypeIndex,
    group_key: groupKey,
    group_properties: {
        name: 'Test Company Inc.',
        industry: 'Technology',
        employees: 150,
    },
    created_at: '2023-01-01T00:00:00.000000Z',
}

const meta: Meta = {
    title: 'Replay/Scenes/Group',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04',
        testOptions: {
            loaderTimeout: 15000,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/environments/:team_id/session_recordings/matching_events': () => [200, { results: [] }],
                '/api/projects/:team_id/groups/related': () => [200, []],
                '/api/projects/:team_id/groups/:group_type_index': () => [200, groupData],
                '/api/projects/:team_id/groups/find': () => [200, groupData],
                '/api/projects/:team_id/groups_types': () => [
                    200,
                    [
                        {
                            group_type_index: 0,
                            group_type: 'company',
                            name_singular: 'Company',
                            name_plural: 'Companies',
                        },
                    ],
                ],
                '/api/environments/:team_id/groups/related': () => [200, []],
                '/api/environments/:team_id/groups/:group_type_index': () => [200, groupData],
                '/api/environments/:team_id/groups/find': () => [200, groupData],
                '/api/environments/:team_id/groups_types': () => [
                    200,
                    [
                        {
                            group_type_index: 0,
                            group_type: 'company',
                            name_singular: 'Company',
                            name_plural: 'Companies',
                        },
                    ],
                ],
                '/api/environments/:team_id/session_recordings/': () => [200, { results: threeRecordings }],
            },
            post: {
                '/api/environments/:team_id/query/': () => [200, { results: [] }],
            },
        }),
    ],
}
export default meta

export const GroupRecordingTabEmpty: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/session_recordings': () => [200, { results: [] }],
        },
    })

    router.actions.push(urls.group(groupTypeIndex, groupKey, true, 'sessionRecordings'))

    return <App />
}

export const GroupRecordingTabMultipleAndNotFound: StoryFn = () => {
    router.actions.push(urls.group(groupTypeIndex, groupKey, true, 'sessionRecordings'))

    return <App />
}

export const GroupRecordingTabMultipleAndFound: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/session_recordings/': () => [200, { results: threeRecordings }],
            '/api/environments/:team_id/session_recordings/:id': () => [
                200,
                { ...recordingMetaJson, id: 'group-rec-002' },
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
            '/api/environments/:team_id/query/': () => [200, { results: [] }],
        },
    })

    router.actions.push(
        combineUrl(urls.group(groupTypeIndex, groupKey, true, 'sessionRecordings'), {
            sessionRecordingId: 'group-rec-002',
            pause: true,
            inspectorSideBar: true,
            tab: 'inspector',
            t: 4,
        }).url
    )

    return <App />
}
GroupRecordingTabMultipleAndFound.parameters = {
    testOptions: {
        waitForSelector: '.PlayerFrame__content .replayer-wrapper iframe',
    },
}
GroupRecordingTabMultipleAndFound.tags = ['test-skip']

export const GroupRecordingTabWide: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/session_recordings/': () => [200, { results: threeRecordings }],
            '/api/environments/:team_id/session_recordings/:id': () => [
                200,
                { ...recordingMetaJson, id: 'group-rec-001' },
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
            '/api/environments/:team_id/query/': () => [200, { results: [] }],
        },
    })

    router.actions.push(
        combineUrl(urls.group(groupTypeIndex, groupKey, true, 'sessionRecordings'), {
            sessionRecordingId: 'group-rec-001',
            pause: true,
            inspectorSideBar: true,
            tab: 'inspector',
            t: 4,
        }).url
    )

    return <App />
}
GroupRecordingTabWide.parameters = {
    testOptions: {
        viewport: { width: 1300, height: 720 },
        waitForSelector: '.PlayerFrame__content .replayer-wrapper iframe',
    },
}
GroupRecordingTabWide.tags = ['test-skip']

export const GroupRecordingTabNarrow: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/session_recordings/': () => [200, { results: threeRecordings }],
            '/api/environments/:team_id/session_recordings/:id': () => [
                200,
                { ...recordingMetaJson, id: 'group-rec-001' },
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
            '/api/environments/:team_id/query/': () => [200, { results: [] }],
        },
    })

    router.actions.push(
        combineUrl(urls.group(groupTypeIndex, groupKey, true, 'sessionRecordings'), {
            sessionRecordingId: 'group-rec-001',
            pause: true,
            inspectorSideBar: true,
            tab: 'inspector',
            t: 4,
        }).url
    )

    return <App />
}
GroupRecordingTabNarrow.parameters = {
    testOptions: {
        viewport: { width: 568, height: 1024 },
        waitForSelector: '.PlayerFrame__content .replayer-wrapper iframe',
    },
}
GroupRecordingTabNarrow.tags = ['test-skip']

export const GroupEventsTabWithModal: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/session_recordings/:id': () => [
                200,
                { ...recordingMetaJson, id: 'group-rec-001' },
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
            '/api/environments/:team_id/query/': () => [200, { results: [] }],
        },
    })

    router.actions.push(
        combineUrl(
            urls.group(groupTypeIndex, groupKey, true, 'events'),
            {
                pause: true,
                inspectorSideBar: true,
                tab: 'inspector',
                t: 4,
            },
            { sessionRecordingId: 'group-rec-001' }
        ).url
    )

    return <App />
}
GroupEventsTabWithModal.parameters = {
    testOptions: {
        waitForSelector: '.PlayerFrame__content .replayer-wrapper iframe',
    },
}
GroupEventsTabWithModal.tags = ['test-skip']

export const GroupEventsTabWithModalNotFound: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/session_recordings/:id': () => [404, { detail: 'Not found.' }],
            '/api/environments/:team_id/session_recordings/:id/snapshots': () => [404, { detail: 'Not found.' }],
        },
        post: {
            '/api/environments/:team_id/query/': () => [200, { results: [] }],
        },
    })

    router.actions.push(`${urls.group(groupTypeIndex, groupKey, true, 'events')}#sessionRecordingId=non-existent`)

    return <App />
}
