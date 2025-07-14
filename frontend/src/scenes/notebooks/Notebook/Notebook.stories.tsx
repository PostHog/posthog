import { Meta, StoryObj } from '@storybook/react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { NotebookType } from '~/types'

import notebook12345Json from './__mocks__/notebook-12345.json'
import { notebookTestTemplate } from './__mocks__/notebook-template-for-snapshot'

// a list of test cases to run, showing different types of content in notebooks
const testCases: Record<string, NotebookType> = {
    'api/projects/:team_id/notebooks/text-formats': notebookTestTemplate('text-formats', [
        {
            type: 'paragraph',
            content: [
                {
                    type: 'text',
                    marks: [
                        {
                            type: 'bold',
                        },
                    ],
                    text: ' bold ',
                },
            ],
        },
        {
            type: 'paragraph',
            content: [
                {
                    type: 'text',
                    marks: [
                        {
                            type: 'italic',
                        },
                    ],
                    text: 'italic',
                },
            ],
        },
        {
            type: 'paragraph',
            content: [
                {
                    type: 'text',
                    marks: [
                        {
                            type: 'bold',
                        },
                        {
                            type: 'italic',
                        },
                    ],
                    text: 'bold _and_ italic',
                },
            ],
        },
        {
            type: 'paragraph',
            content: [
                {
                    type: 'text',
                    marks: [
                        {
                            type: 'code',
                        },
                    ],
                    text: 'code',
                },
            ],
        },
    ]),
    'api/projects/:team_id/notebooks/headings': notebookTestTemplate('headings', [
        {
            type: 'heading',
            attrs: {
                level: 1,
            },
            content: [
                {
                    type: 'text',
                    text: 'Heading 1',
                },
            ],
        },
        {
            type: 'heading',
            attrs: {
                level: 2,
            },
            content: [
                {
                    type: 'text',
                    text: 'Heading 2',
                },
            ],
        },
        {
            type: 'heading',
            attrs: {
                level: 3,
            },
            content: [
                {
                    type: 'text',
                    text: 'Heading 3',
                },
            ],
        },
    ]),
    'api/projects/:team_id/notebooks/numbered-list': notebookTestTemplate('numbered-list', [
        {
            type: 'orderedList',
            content: [
                {
                    type: 'listItem',
                    content: [
                        {
                            type: 'paragraph',
                            content: [
                                {
                                    type: 'text',
                                    text: 'first item',
                                },
                            ],
                        },
                    ],
                },
                {
                    type: 'listItem',
                    content: [
                        {
                            type: 'paragraph',
                            content: [
                                {
                                    type: 'text',
                                    text: 'second item',
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    ]),
    'api/projects/:team_id/notebooks/bullet-list': notebookTestTemplate('bullet-list', [
        {
            type: 'bulletList',
            content: [
                {
                    type: 'listItem',
                    content: [
                        {
                            type: 'paragraph',
                            content: [
                                {
                                    type: 'text',
                                    text: 'first item',
                                },
                            ],
                        },
                    ],
                },
                {
                    type: 'listItem',
                    content: [
                        {
                            type: 'paragraph',
                            content: [
                                {
                                    type: 'text',
                                    text: 'second item',
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    ]),
    'api/projects/:team_id/notebooks/recordings-playlist': notebookTestTemplate('recordings-playlist', [
        {
            type: 'ph-recording-playlist',
            attrs: {
                height: null,
                title: 'Session replays',
                nodeId: '41faad12-499f-4a4b-95f7-3a36601317cc',
                filters:
                    '{"session_recording_duration":{"type":"recording","key":"duration","value":3600,"operator":"gt"},"properties":[],"events":[],"actions":[],"date_from":"-7d","date_to":null}',
            },
        },
    ]),
    'api/projects/:team_id/notebooks/empty': notebookTestTemplate('empty', []),
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Notebooks',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04', // To stabilize relative dates
        pageUrl: urls.notebooks(),
    },
    decorators: [
        mswDecorator({
            post: {
                'api/environments/:team_id/query': {
                    clickhouse:
                        "SELECT nullIf(nullIf(events.`$session_id`, ''), 'null') AS session_id, any(events.properties) AS properties FROM events WHERE and(equals(events.team_id, 1), in(events.event, [%(hogql_val_0)s, %(hogql_val_1)s]), ifNull(in(session_id, [%(hogql_val_2)s]), 0), ifNull(greaterOrEquals(toTimeZone(events.timestamp, %(hogql_val_3)s), %(hogql_val_4)s), 0), ifNull(lessOrEquals(toTimeZone(events.timestamp, %(hogql_val_5)s), %(hogql_val_6)s), 0)) GROUP BY session_id LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
                    columns: ['session_id', 'properties'],
                    hogql: "SELECT properties.$session_id AS session_id, any(properties) AS properties FROM events WHERE and(in(event, ['$pageview', '$autocapture']), in(session_id, ['018a8a51-a39d-7b18-897f-94054eec5f61']), greaterOrEquals(timestamp, '2023-09-11 16:55:36'), lessOrEquals(timestamp, '2023-09-13 18:07:40')) GROUP BY session_id LIMIT 100",
                    query: "SELECT properties.$session_id as session_id, any(properties) as properties\n                                FROM events\n                                WHERE event IN ['$pageview', '$autocapture']\n                                AND session_id IN ['018a8a51-a39d-7b18-897f-94054eec5f61']\n                                -- the timestamp range here is only to avoid querying too much of the events table\n                                -- we don't really care about the absolute value, \n                                -- but we do care about whether timezones have an odd impact\n                                -- so, we extend the range by a day on each side so that timezones don't cause issues\n                                AND timestamp >= '2023-09-11 16:55:36'\n                                AND timestamp <= '2023-09-13 18:07:40'\n                                GROUP BY session_id",
                    results: [
                        [
                            '018a8a51-a39d-7b18-897f-94054eec5f61',
                            '{"$os":"Mac OS X","$os_version":"10.15.7","$browser":"Chrome","$device_type":"Desktop","$current_url":"http://localhost:8000/ingestion/platform","$host":"localhost:8000","$pathname":"/ingestion/platform","$browser_version":116,"$browser_language":"en-GB","$screen_height":982,"$screen_width":1512,"$viewport_height":827,"$viewport_width":1498,"$lib":"web","$lib_version":"1.78.2","$insert_id":"249xj40dkv7x9knp","$time":1694537723.201,"distinct_id":"uLI7S0z6rWQIKAjgXhdUBplxPYymuQqxH5QbJKe2wqr","$device_id":"018a8a51-a39c-78f9-a4e4-1183f059f7cc","$user_id":"uLI7S0z6rWQIKAjgXhdUBplxPYymuQqxH5QbJKe2wqr","is_demo_project":false,"$groups":{"project":"018a8a51-9ee3-0000-0369-ff1924dcba89","organization":"018a8a51-988e-0000-d3e6-477c7cc111f1","instance":"http://localhost:8000"},"$autocapture_disabled_server_side":false,"$active_feature_flags":[],"$feature_flag_payloads":{},"realm":"hosted-clickhouse","email_service_available":false,"slack_service_available":false,"$referrer":"http://localhost:8000/signup","$referring_domain":"localhost:8000","$event_type":"click","$ce_version":1,"token":"phc_awewGgfgakHbaSbprHllKajqoa6iP2nz7OAUou763ie","$session_id":"018a8a51-a39d-7b18-897f-94054eec5f61","$window_id":"018a8a51-a39d-7b18-897f-940673bea28c","$set_once":{"$initial_os":"Mac OS X","$initial_browser":"Chrome","$initial_device_type":"Desktop","$initial_current_url":"http://localhost:8000/ingestion/platform","$initial_pathname":"/ingestion/platform","$initial_browser_version":116,"$initial_referrer":"http://localhost:8000/signup","$initial_referring_domain":"localhost:8000"},"$sent_at":"2023-09-12T16:55:23.743000+00:00","$ip":"127.0.0.1","$group_0":"018a8a51-9ee3-0000-0369-ff1924dcba89","$group_1":"018a8a51-988e-0000-d3e6-477c7cc111f1","$group_2":"http://localhost:8000"}',
                        ],
                    ],
                    types: [
                        ['session_id', 'Nullable(String)'],
                        ['properties', 'String'],
                    ],
                },
            },
            get: {
                'api/projects/:team_id/notebooks': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: '01891c30-e217-0000-f8af-fd0995850693',
                            short_id: 'TzPqJ307',
                            title: 'testing my notebook wat',
                            content: {
                                type: 'doc',
                                content: [
                                    {
                                        type: 'heading',
                                        attrs: {
                                            level: 1,
                                        },
                                        content: [
                                            {
                                                text: 'testing my notebook wat',
                                                type: 'text',
                                            },
                                        ],
                                    },
                                ],
                            },
                            version: 13,
                            deleted: false,
                            created_at: '2023-07-03T14:38:32.984546Z',
                            created_by: {
                                id: 1,
                                uuid: '0188ea22-05ae-0000-6d0b-d47602552d2c',
                                distinct_id: 'wnATPtp3kGKinrPUTgGGuR80MmuzrJLRwzGgtoJCt4V',
                                first_name: 'Paul',
                                email: 'paul@posthog.com',
                                is_email_verified: false,
                            },
                            last_modified_at: '2023-07-03T17:03:51.166530Z',
                            last_modified_by: {
                                id: 1,
                                uuid: '0188ea22-05ae-0000-6d0b-d47602552d2c',
                                distinct_id: 'wnATPtp3kGKinrPUTgGGuR80MmuzrJLRwzGgtoJCt4V',
                                first_name: 'Paul',
                                email: 'paul@posthog.com',
                                is_email_verified: false,
                            },
                        },
                    ],
                },
                'api/projects/:team_id/notebooks/12345': notebook12345Json,
                'api/environments/:team_id/session_recordings': {
                    results: [
                        {
                            id: '018a8a51-a39d-7b18-897f-94054eec5f61',
                            distinct_id: 'uLI7S0z6rWQIKAjgXhdUBplxPYymuQqxH5QbJKe2wqr',
                            viewed: true,
                            recording_duration: 4324,
                            active_seconds: 21,
                            inactive_seconds: 4302,
                            start_time: '2023-09-12T16:55:36.404000Z',
                            end_time: '2023-09-12T18:07:40.147000Z',
                            click_count: 3,
                            keypress_count: 0,
                            mouse_activity_count: 924,
                            console_log_count: 37,
                            console_warn_count: 7,
                            console_error_count: 9,
                            start_url: 'http://localhost:8000/replay/recent',
                            person: {
                                id: 1,
                                name: 'paul@posthog.com',
                                distinct_ids: [
                                    'uLI7S0z6rWQIKAjgXhdUBplxPYymuQqxH5QbJKe2wqr',
                                    '018a8a51-a39c-78f9-a4e4-1183f059f7cc',
                                ],
                                properties: {
                                    email: 'paul@posthog.com',
                                    $initial_os: 'Mac OS X',
                                    $geoip_latitude: -33.8715,
                                    $geoip_city_name: 'Sydney',
                                    $geoip_longitude: 151.2006,
                                    $geoip_time_zone: 'Australia/Sydney',
                                    $initial_browser: 'Chrome',
                                    $initial_pathname: '/',
                                    $initial_referrer: 'http://localhost:8000/signup',
                                    $geoip_postal_code: '2000',
                                    $creator_event_uuid: '018a8a51-a39d-7b18-897f-9407e795547b',
                                    $geoip_country_code: 'AU',
                                    $geoip_country_name: 'Australia',
                                    $initial_current_url: 'http://localhost:8000/',
                                    $initial_device_type: 'Desktop',
                                    $geoip_continent_code: 'OC',
                                    $geoip_continent_name: 'Oceania',
                                    $initial_geoip_latitude: -33.8715,
                                    $initial_browser_version: 116,
                                    $initial_geoip_city_name: 'Sydney',
                                    $initial_geoip_longitude: 151.2006,
                                    $initial_geoip_time_zone: 'Australia/Sydney',
                                    $geoip_subdivision_1_code: 'NSW',
                                    $geoip_subdivision_1_name: 'New South Wales',
                                    $initial_referring_domain: 'localhost:8000',
                                    $initial_geoip_postal_code: '2000',
                                    $initial_geoip_country_code: 'AU',
                                    $initial_geoip_country_name: 'Australia',
                                    $initial_geoip_continent_code: 'OC',
                                    $initial_geoip_continent_name: 'Oceania',
                                    $initial_geoip_subdivision_1_code: 'NSW',
                                    $initial_geoip_subdivision_1_name: 'New South Wales',
                                },
                                created_at: '2023-09-12T16:55:20.736000Z',
                                uuid: '018a8a51-a3d3-0000-e8fa-94621f9ddd48',
                            },
                            storage: 'clickhouse',
                        },
                    ],
                    has_next: false,
                    version: 3,
                },
                ...testCases,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const NotebooksList: Story = {}
export const Headings: Story = { parameters: { pageUrl: urls.notebook('headings') } }
export const TextFormats: Story = { parameters: { pageUrl: urls.notebook('text-formats') } }
export const NumberedList: Story = { parameters: { pageUrl: urls.notebook('numbered-list') } }
export const BulletList: Story = { parameters: { pageUrl: urls.notebook('bullet-list') } }
export const TextOnlyNotebook: Story = { parameters: { pageUrl: urls.notebook('12345') } }
export const EmptyNotebook: Story = { parameters: { pageUrl: urls.notebook('empty') } }
export const NotebookNotFound: Story = { parameters: { pageUrl: urls.notebook('abcde') } }

export const RecordingsPlaylist: Story = {
    parameters: {
        pageUrl: urls.notebook('recordings-playlist'),
        testOptions: {
            waitForSelector: '.NotebookNode__content', // All stories with widget-style nodes needs this
        },
    },
}
