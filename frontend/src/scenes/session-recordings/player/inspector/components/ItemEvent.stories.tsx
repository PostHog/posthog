import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { uuid } from 'lib/utils'
import {
    ItemEvent,
    ItemEventDetail,
    ItemEventProps,
} from 'scenes/session-recordings/player/inspector/components/ItemEvent'
import { InspectorListItemEvent } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { mswDecorator } from '~/mocks/browser'
import { RecordingEventType } from '~/types'

type Story = StoryObj<typeof ItemEvent>
const meta: Meta<typeof ItemEvent> = {
    title: 'Components/PlayerInspector/ItemEvent',
    component: ItemEvent,
    decorators: [
        mswDecorator({
            get: {},
        }),
    ],
    parameters: {
        mockDate: '2025-09-23',
    },
}
export default meta

function makeItem(
    itemOverrides: Partial<InspectorListItemEvent> = {},
    dataOverrides: Partial<RecordingEventType> = {},
    propertiesOverrides: Record<string, any> = {}
): InspectorListItemEvent {
    const mockDate = dayjs('2025-11-04')
    const data: RecordingEventType = {
        elements: [],
        event: '',
        fullyLoaded: true,
        id: '',
        playerTime: 0,

        timestamp: mockDate.toISOString(),
        ...dataOverrides,
        // this is last so that it overrides data overrides sensibly 🙃
        properties: {
            ...propertiesOverrides,
        },
    }
    return {
        data: data,
        search: '',
        timeInRecording: 0,
        timestamp: mockDate,
        type: 'events',
        key: `some-key-${uuid()}`,
        ...itemOverrides,
    }
}

const BasicTemplate: StoryFn<typeof ItemEvent> = (props: Partial<ItemEventProps>) => {
    props.item = props.item || makeItem(undefined, { event: 'A long event name if no other name is provided' })

    const propsToUse = props as ItemEventProps

    return (
        <div className="flex flex-col gap-2 min-w-96">
            <h3>Collapsed</h3>
            <ItemEvent {...propsToUse} />
            <LemonDivider />
            <h3>Expanded</h3>
            <ItemEventDetail {...propsToUse} />
            <LemonDivider />
            <h3>Collapsed with overflowing text</h3>
            <div className="w-20">
                <ItemEvent {...propsToUse} />
            </div>
        </div>
    )
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}

export const PageViewWithPath: Story = BasicTemplate.bind({})
PageViewWithPath.args = {
    item: makeItem(
        {},
        { event: '$pageview' },
        { $pathname: '/some/path', aBool: true, aNumber: 123, aString: 'hello', aNull: null, anUndefined: undefined }
    ),
}

export const PageViewWithCurrentURL: Story = BasicTemplate.bind({})
PageViewWithCurrentURL.args = {
    item: makeItem({}, { event: '$pageview' }, { $current_url: 'https://my-site.io/some/path' }),
}

export const ErrorEvent: Story = BasicTemplate.bind({})
ErrorEvent.args = {
    item: makeItem(
        {},
        { event: '$exception' },
        {
            $exception_message: 'Something went wrong',
            $exception_type: 'Error',
            $exception_personURL: 'https://my-site.io/person/123',
            $lib: 'web',
            $lib_version: '1.187.234',
            $browser: 'Chrome',
            $browser_version: 180,
            $os: 'Windows',
            $os_version: '11',
        }
    ),
}

export const SentryErrorEvent: Story = BasicTemplate.bind({})
SentryErrorEvent.args = {
    item: makeItem(
        {},
        { event: '$exception' },
        {
            $sentry_url: 'https://some-sentry-url',
            $exception_message: 'Something went wrong',
            $exception_type: 'Error',
            $exception_personURL: 'https://my-site.io/person/123',
            $lib: 'web',
            $lib_version: '1.187.234',
            $browser: 'Chrome',
            $browser_version: 180,
            $os: 'Windows',
            $os_version: '11',
        }
    ),
}

export const WebVitalsEvent: Story = BasicTemplate.bind({})
WebVitalsEvent.args = {
    item: makeItem(
        {},
        { event: '$web_vitals' },
        {
            $os: 'Mac OS X',
            $os_version: '10.15.7',
            $browser: 'Chrome',
            $device_type: 'Desktop',
            $current_url: 'http://localhost:8000/project/1/activity/explore',
            $browser_version: 126,
            $browser_language: 'en-GB',
            $lib: 'web',
            $lib_version: '1.141.4',
            $web_vitals_enabled_server_side: false,
            $web_vitals_INP_event: {
                name: 'INP',
                value: 72,
                rating: 'good',
                delta: 72,
                entries: [{}, {}],
                id: 'v4-1719484470693-6845621238957',
                navigationType: 'reload',
                $current_url: 'http://localhost:8000/project/1/activity/explore',
                $session_id: '01900000-0000-0000-0000-000000000001',
                $window_id: '01900000-0000-0000-0000-000000000002',
                timestamp: 1719484490693,
            },
            $web_vitals_INP_value: 72,
            $web_vitals_CLS_event: {
                name: 'CLS',
                value: 0.10656105463687347,
                rating: 'needs-improvement',
                delta: 0.10656105463687347,
                entries: [{}, {}, {}, {}, {}, {}, {}, {}, {}],
                id: 'v4-1719484470710-6118725051157',
                navigationType: 'reload',
                $current_url: 'http://localhost:8000/project/1/activity/explore',
                $session_id: '01900000-0000-0000-0000-000000000001',
                $window_id: '01900000-0000-0000-0000-000000000002',
                timestamp: 1719484490693,
            },
            $web_vitals_CLS_value: 0.10656105463687347,
        }
    ),
}

export const GroupIdentifyEvent: Story = BasicTemplate.bind({})
GroupIdentifyEvent.args = {
    item: makeItem(
        {},
        { event: '$groupidentify' },
        {
            $os: 'Mac OS X',
            $os_version: '10.15.7',
            $browser: 'Chrome',
            $device_type: 'Desktop',
            $current_url: 'https://us.posthog.com/project/2/insights/new',
            $host: 'us.posthog.com',
            $pathname: '/project/2/insights/new',
            $initial_person_info: {
                r: '$direct',
                u: 'https://us.posthog.com/project/2',
            },
            $groups: {
                project: '00000000-0000-0000-0000-proj00000001',
                organization: '00000000-0000-0000-0000-org000000001',
                customer: 'cus_ExampleCustomer123',
                instance: 'https://us.posthog.com',
            },
            $group_type: 'instance',
            $group_key: 'https://us.posthog.com',
            $group_set: {
                site_url: 'https://us.posthog.com',
            },
            $session_id: '01900000-0000-0000-0000-000000000003',
            $window_id: '01900000-0000-0000-0000-000000000004',
            $group_2: '00000000-0000-0000-0000-proj00000001',
            $group_0: '00000000-0000-0000-0000-org000000001',
            $group_3: 'cus_ExampleCustomer123',
            $group_1: 'https://us.posthog.com',
        }
    ),
}

export const AISpanEvent: Story = BasicTemplate.bind({})
AISpanEvent.args = {
    item: makeItem(
        {},
        { event: '$ai_span' },
        {
            $timestamp: '2025-09-21T14:21:52.895Z',
            region: 'US',
            conversation_id: '00000000-0000-0000-0000-000000000005',
            $session_id: '01900000-0000-0000-0000-000000000006',
            $groups: {
                instance: 'https://us.posthog.com',
                organization: '00000000-0000-0000-0000-org000000002',
                project: '00000000-0000-0000-0000-proj00000002',
            },
            $geoip_disable: true,
            $ai_input_state: {
                dashboard_name: null,
                graph_status: null,
                intermediate_steps: null,
                memory_collection_messages: null,
                messages: [
                    {
                        content: 'modify this query and give me for cohort 1001 and 1002',
                        id: '37130538-7a64-452c-b742-0febacea07e2',
                        type: 'human',
                        ui_context: null,
                    },
                    {
                        content: '',
                        id: 'bfbdd016-01c3-401d-901c-1475688f982d',
                        meta: null,
                        tool_calls: [
                            {
                                args: {
                                    instructions:
                                        'Modify the query to return results for both cohort 1001 and cohort 1002. Group by cohort, as well as day, and show the cohort ID in the results. All other logic should remain the same.',
                                },
                                id: 'call_a8sMElJzxA53Acb9AguyjOg1',
                                name: 'generate_hogql_query',
                                type: 'tool_call',
                            },
                        ],
                        type: 'ai',
                    },
                    {
                        content:
                            "```sql\nSELECT\n    cohort_id,\n    day,\n    sum(session_duration) AS total_session_time_seconds,\n    count() AS total_sessions,\n    count(distinct person_id) AS total_unique_users\nFROM (\n    SELECT\n        toDate(timestamp) AS day,\n        $session_id,\n        person_id,\n        multiIf(person_id IN COHORT 1001, 1001, person_id IN COHORT 1002, 1002, NULL) AS cohort_id,\n        dateDiff('second', min(timestamp), max(timestamp)) AS session_duration\n    FROM events\n    WHERE event = 'page_viewed'\n        AND timestamp >= now() - interval 3 day\n        AND (person_id IN COHORT 1001 OR person_id IN COHORT 1002)\n    GROUP BY day, $session_id, person_id, cohort_id\n)\nGROUP BY cohort_id, day\nORDER BY cohort_id, day DESC\n```",
                        id: '9eac3e81-4f62-41ae-95fc-3064f03148cd',
                        tool_call_id: 'call_a8sMElJzxA53Acb9AguyjOg1',
                        type: 'tool',
                        ui_payload: {
                            generate_hogql_query:
                                "SELECT\n    cohort_id,\n    day,\n    sum(session_duration) AS total_session_time_seconds,\n    count() AS total_sessions,\n    count(distinct person_id) AS total_unique_users\nFROM (\n    SELECT\n        toDate(timestamp) AS day,\n        $session_id,\n        person_id,\n        multiIf(person_id IN COHORT 1001, 1001, person_id IN COHORT 1002, 1002, NULL) AS cohort_id,\n        dateDiff('second', min(timestamp), max(timestamp)) AS session_duration\n    FROM events\n    WHERE event = 'page_viewed'\n        AND timestamp >= now() - interval 3 day\n        AND (person_id IN COHORT 1001 OR person_id IN COHORT 1002)\n    GROUP BY day, $session_id, person_id, cohort_id\n)\nGROUP BY cohort_id, day\nORDER BY cohort_id, day DESC",
                        },
                        visible: false,
                    },
                    {
                        content:
                            'The query is now updated to return results for both cohort 1001 and cohort 1002, grouped by cohort and day, with the cohort ID shown in the results. All other logic remains the same.',
                        id: 'b80799bc-d796-45f3-aaaf-262190a80ca4',
                        meta: null,
                        tool_calls: [],
                        type: 'ai',
                    },
                ],
                notebook_short_id: null,
                onboarding_question: null,
                plan: null,
                query_generation_retry_count: 0,
                query_planner_intermediate_messages: null,
                query_planner_previous_response_id: null,
                rag_context: null,
                root_conversation_start_id: null,
                root_tool_call_id: null,
                root_tool_calls_count: 1,
                root_tool_insight_plan: null,
                root_tool_insight_type: null,
                search_insights_queries: null,
                search_insights_query: null,
                selected_insight_ids: null,
                session_summarization_query: null,
                should_use_current_filters: null,
                start_id: '37130538-7a64-452c-b742-0febacea07e2',
                summary_title: null,
            },
            $lib: 'posthog-python',
            $ai_output_state: {
                dashboard_name: null,
                graph_status: null,
                intermediate_steps: null,
                memory_collection_messages: null,
                messages: [],
                notebook_short_id: null,
                onboarding_question: null,
                plan: null,
                query_generation_retry_count: 0,
                query_planner_intermediate_messages: null,
                query_planner_previous_response_id: null,
                rag_context: null,
                root_conversation_start_id: null,
                root_tool_call_id: null,
                root_tool_calls_count: 0,
                root_tool_insight_plan: null,
                root_tool_insight_type: null,
                search_insights_queries: null,
                search_insights_query: null,
                selected_insight_ids: null,
                session_summarization_query: null,
                should_use_current_filters: null,
                start_id: null,
                summary_title: null,
            },
            assistant_mode: 'assistant',
            $ai_span_name: 'root_tools',
            is_first_conversation: true,
            $python_version: '3.11.11',
            $ai_span_id: 'span-0001-0001-0001-000000000001',
            $python_runtime: 'CPython',
            $ai_latency: 0.039714813232421875,
            $lib_version: '6.7.4',
            $ai_parent_id: 'trace-0001-0001-0001-000000000001',
            $ai_trace_id: 'trace-0001-0001-0001-000000000001',
            $os: 'Linux',
            $os_version: '12',
            $ip: '192.168.1.1',
            $lib_version__major: 6,
            $lib_version__minor: 7,
            $lib_version__patch: 4,
            num_keys_in_properties: 469,
            $group_1: 'https://us.posthog.com',
            $group_0: '00000000-0000-0000-0000-org000000002',
            $group_2: '00000000-0000-0000-0000-proj00000002',
        }
    ),
}

export const AIGenerationEvent: Story = BasicTemplate.bind({})
AIGenerationEvent.args = {
    item: makeItem(
        {},
        { event: '$ai_generation' },
        {
            $timestamp: '2025-09-21T14:02:44.058Z',
            $ai_http_status: 200,
            $ai_input: [
                {
                    content:
                        "You are Max, PostHog's AI assistant. Be friendly, direct, and helpful. Use tools to analyze data and answer questions.",
                    role: 'system',
                },
                {
                    content: 'Core memory: Track user interactions with buttons and URLs using autocapture events.',
                    role: 'system',
                },
                {
                    content: 'User is editing SQL. Use generate_hogql_query tool for SQL queries.',
                    role: 'system',
                },
                {
                    content: 'Navigate between pages using the navigate tool.',
                    role: 'system',
                },
                {
                    content:
                        'You are currently in project Example Project, which is part of the Example Organization.\nThe user\'s name appears to be Jane Doe (jane@example.com). Feel free to use their first name when greeting. DO NOT use this name if it appears possibly fake.\nThe user is accessing the PostHog App from the "us" region, therefore all PostHog App URLs should be prefixed with the region, e.g. https://us.posthog.com\nCurrent time in the project\'s timezone, UTC: 2025-09-21 14:02:43.',
                    role: 'system',
                },
                {
                    content: 'sql for how many people clicked button with text containg submit on the url with /upload',
                    role: 'user',
                },
                {
                    content: '',
                    role: 'assistant',
                    tool_calls: [
                        {
                            function: {
                                arguments:
                                    '{"instructions": "Count the number of distinct users (person_id) who triggered an autocapture event where element_text contains \'submit\' and $current_url contains \'/upload\' (case-insensitive)."}',
                                name: 'generate_hogql_query',
                            },
                            id: 'call_kS45Oc4e5FV19MjLy61Y2xyC',
                            type: 'function',
                        },
                    ],
                },
                {
                    content:
                        "```sql\nSELECT count(DISTINCT person_id)\nFROM events\nWHERE event = '$autocapture'\n  AND lower(properties.element_text) LIKE '%submit%'\n  AND lower(properties.$current_url) LIKE '%/upload%'\n  AND timestamp >= now() - INTERVAL 30 DAY\n```",
                    role: 'tool',
                },
            ],
            $ai_span_id: 'span-0002-0002-0002-000000000002',
            $groups: {
                instance: 'https://us.posthog.com',
                organization: '00000000-0000-0000-0000-org000000003',
                project: '00000000-0000-0000-0000-proj00000003',
            },
            $ai_input_tokens: 3978,
            $python_runtime: 'CPython',
            $ai_parent_id: 'trace-0002-0002-0002-000000000002',
            assistant_mode: 'assistant',
            $ai_span_name: 'MaxChatOpenAI',
            $ai_latency: 0.9990310668945312,
            $lib_version: '6.7.4',
            $ai_reasoning_tokens: 0,
            $os: 'Linux',
            $geoip_disable: true,
            conversation_id: '00000000-0000-0000-0000-000000000007',
            $python_version: '3.11.11',
            $ai_output_choices: [
                {
                    content:
                        'This query counts the number of distinct users who clicked a button with text containing "submit" on any URL containing "/upload" in the last 30 days. Let me know if you want to adjust the time range or see more details.',
                    role: 'assistant',
                },
            ],
            $ai_model_parameters: {
                stream: true,
                temperature: 0.3,
            },
            $ai_cache_creation_input_tokens: 0,
            $ai_cache_read_input_tokens: 3200,
            $ai_model: 'gpt-4.1',
            $lib: 'posthog-python',
            is_first_conversation: true,
            $ai_base_url: null,
            region: 'US',
            $session_id: '01900000-0000-0000-0000-000000000008',
            $os_version: '12',
            $ai_trace_id: 'trace-0002-0002-0002-000000000002',
            $ai_output_tokens: 49,
            $ai_provider: 'openai',
            $ip: '192.168.1.2',
            $lib_version__major: 6,
            $lib_version__minor: 7,
            $lib_version__patch: 4,
            num_keys_in_properties: 480,
            $ai_model_cost_used: 'gpt-4.1',
            $ai_input_cost_usd: 0.003156,
            $ai_output_cost_usd: 0.000392,
            $ai_total_cost_usd: 0.003548,
            $ai_temperature: 0.3,
            $ai_stream: true,
            $group_1: 'https://us.posthog.com',
            $group_0: '00000000-0000-0000-0000-org000000003',
            $group_2: '00000000-0000-0000-0000-proj00000003',
        }
    ),
}

export const AITraceEvent: Story = BasicTemplate.bind({})
AITraceEvent.args = {
    item: makeItem(
        {},
        { event: '$ai_trace' },
        {
            $timestamp: '2025-09-21T14:02:44.168Z',
            conversation_id: '00000000-0000-0000-0000-000000000009',
            $ai_span_name: 'LangGraph',
            assistant_mode: 'assistant',
            $ai_trace_id: 'trace-0003-0003-0003-000000000003',
            $os_version: '12',
            $os: 'Linux',
            $session_id: '01900000-0000-0000-0000-000000000010',
            region: 'US',
            $ai_output_state: {
                graph_status: null,
                memory_collection_messages: null,
                messages: [
                    {
                        content:
                            'sql for how many people clicked button with text containg submit on the url with /upload',
                        id: 'msg-0001-0001-0001-000000000001',
                        type: 'human',
                        ui_context: null,
                    },
                    {
                        content: '',
                        id: 'msg-0001-0001-0001-000000000002',
                        meta: null,
                        tool_calls: [
                            {
                                args: {
                                    instructions:
                                        "Count the number of distinct users (person_id) who triggered an autocapture event where element_text contains 'submit' and $current_url contains '/upload' (case-insensitive).",
                                },
                                id: 'call_ExampleCallId001',
                                name: 'generate_hogql_query',
                                type: 'tool_call',
                            },
                        ],
                        type: 'ai',
                    },
                    {
                        content:
                            "```sql\nSELECT count(DISTINCT person_id)\nFROM events\nWHERE event = '$autocapture'\n  AND lower(properties.element_text) LIKE '%submit%'\n  AND lower(properties.$current_url) LIKE '%/upload%'\n  AND timestamp >= now() - INTERVAL 30 DAY\n```",
                        id: 'msg-0001-0001-0001-000000000003',
                        tool_call_id: 'call_ExampleCallId001',
                        type: 'tool',
                        ui_payload: {
                            generate_hogql_query:
                                "SELECT count(DISTINCT person_id)\nFROM events\nWHERE event = '$autocapture'\n  AND lower(properties.element_text) LIKE '%submit%'\n  AND lower(properties.$current_url) LIKE '%/upload%'\n  AND timestamp >= now() - INTERVAL 30 DAY",
                        },
                        visible: false,
                    },
                    {
                        content:
                            'This query counts the number of distinct users who clicked a button with text containing "submit" on any URL containing "/upload" in the last 30 days. Let me know if you want to adjust the time range or see more details.',
                        id: 'msg-0001-0001-0001-000000000004',
                        meta: null,
                        tool_calls: [],
                        type: 'ai',
                    },
                ],
                query_generation_retry_count: 0,
                rag_context: null,
                root_conversation_start_id: null,
                root_tool_calls_count: 0,
                start_id: 'msg-0001-0001-0001-000000000001',
            },
            $lib_version: '6.7.4',
            $groups: {
                instance: 'https://us.posthog.com',
                organization: '00000000-0000-0000-0000-org000000004',
                project: '00000000-0000-0000-0000-proj00000004',
            },
            $ai_latency: 11.21250057220459,
            $python_runtime: 'CPython',
            is_first_conversation: true,
            $geoip_disable: true,
            $lib: 'posthog-python',
            $ai_span_id: 'span-0003-0003-0003-000000000003',
            $ai_input_state: {
                dashboard_name: null,
                graph_status: null,
                intermediate_steps: null,
                memory_collection_messages: null,
                messages: [
                    {
                        content:
                            'sql for how many people clicked button with text containg submit on the url with /upload',
                        id: 'msg-0001-0001-0001-000000000001',
                        type: 'human',
                        ui_context: null,
                    },
                ],
                notebook_short_id: null,
                onboarding_question: null,
                plan: null,
                query_generation_retry_count: 0,
                query_planner_intermediate_messages: null,
                query_planner_previous_response_id: null,
                rag_context: null,
                root_conversation_start_id: null,
                root_tool_call_id: null,
                root_tool_calls_count: null,
                root_tool_insight_plan: null,
                root_tool_insight_type: null,
                search_insights_queries: null,
                search_insights_query: null,
                selected_insight_ids: null,
                session_summarization_query: null,
                should_use_current_filters: null,
                start_id: 'msg-0001-0001-0001-000000000001',
                summary_title: null,
            },
            $python_version: '3.11.11',
            $ip: '192.168.1.3',
            $lib_version__major: 6,
            $lib_version__minor: 7,
            $lib_version__patch: 4,
            num_keys_in_properties: 468,
            $group_1: 'https://us.posthog.com',
            $group_0: '00000000-0000-0000-0000-org000000004',
            $group_2: '00000000-0000-0000-0000-proj00000004',
        }
    ),
}
