import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { now } from 'lib/dayjs'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
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
}
export default meta

function makeItem(
    itemOverrides: Partial<InspectorListItemEvent> = {},
    dataOverrides: Partial<RecordingEventType> = {},
    propertiesOverrides: Record<string, any> = {}
): InspectorListItemEvent {
    const data: RecordingEventType = {
        elements: [],
        event: '',
        fullyLoaded: true,
        id: '',
        playerTime: 0,

        timestamp: now().toISOString(),
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
        timestamp: now(),
        type: 'events',
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
    item: makeItem({}, { event: '$pageview' }, { $pathname: '/some/path' }),
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
                $session_id: '0190593b-0f3c-7e04-846a-f3515aa31c2f',
                $window_id: '01905942-b7ba-7c05-85d3-5d7548868b44',
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
                $session_id: '0190593b-0f3c-7e04-846a-f3515aa31c2f',
                $window_id: '01905942-b7ba-7c05-85d3-5d7548868b44',
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
                project: 'fc445b88-e2c4-488e-bb52-aa80cd7918c9',
                organization: '4dc8564d-bd82-1065-2f40-97f7c50f67cf',
                customer: 'cus_IK2DWsWVn2ZM16',
                instance: 'https://us.posthog.com',
            },
            $group_type: 'instance',
            $group_key: 'https://us.posthog.com',
            $group_set: {
                site_url: 'https://us.posthog.com',
            },
            $session_id: '01917043-b2a1-7c2e-a57e-6db514bde084',
            $window_id: '01917043-b2a1-7c2e-a57e-6db6676bb4a1',
            $group_2: 'fc445b88-e2c4-488e-bb52-aa80cd7918c9',
            $group_0: '4dc8564d-bd82-1065-2f40-97f7c50f67cf',
            $group_3: 'cus_IK2DWsWVn2ZM16',
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
            conversation_id: '4c4c28b2-2413-4e3a-adb9-ac9f82b9fb6c',
            $session_id: '01996ca0-c71e-7fe1-85d7-4ea666b9d674',
            $groups: {
                instance: 'https://us.posthog.com',
                organization: '0195658a-abe2-0000-4cda-4b4d999ef970',
                project: '0195658a-abf5-0000-977f-da4270beff18',
            },
            $geoip_disable: true,
            $ai_input_state: {
                dashboard_name: null,
                graph_status: null,
                intermediate_steps: null,
                memory_collection_messages: null,
                messages: [
                    {
                        content: 'modify this query and give me for cohort 181727 and 181725',
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
                                        'Modify the query to return results for both cohort 181727 and cohort 181725. Group by cohort, as well as day, and show the cohort ID in the results. All other logic should remain the same.',
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
                            "```sql\nSELECT\n    cohort_id,\n    day,\n    sum(session_duration) AS total_session_time_seconds,\n    count() AS total_sessions,\n    count(distinct person_id) AS total_unique_users\nFROM (\n    SELECT\n        toDate(timestamp) AS day,\n        $session_id,\n        person_id,\n        multiIf(person_id IN COHORT 181727, 181727, person_id IN COHORT 181725, 181725, NULL) AS cohort_id,\n        dateDiff('second', min(timestamp), max(timestamp)) AS session_duration\n    FROM events\n    WHERE event = 'page_viewed'\n        AND timestamp >= now() - interval 3 day\n        AND (person_id IN COHORT 181727 OR person_id IN COHORT 181725)\n    GROUP BY day, $session_id, person_id, cohort_id\n)\nGROUP BY cohort_id, day\nORDER BY cohort_id, day DESC\n```",
                        id: '9eac3e81-4f62-41ae-95fc-3064f03148cd',
                        tool_call_id: 'call_a8sMElJzxA53Acb9AguyjOg1',
                        type: 'tool',
                        ui_payload: {
                            generate_hogql_query:
                                "SELECT\n    cohort_id,\n    day,\n    sum(session_duration) AS total_session_time_seconds,\n    count() AS total_sessions,\n    count(distinct person_id) AS total_unique_users\nFROM (\n    SELECT\n        toDate(timestamp) AS day,\n        $session_id,\n        person_id,\n        multiIf(person_id IN COHORT 181727, 181727, person_id IN COHORT 181725, 181725, NULL) AS cohort_id,\n        dateDiff('second', min(timestamp), max(timestamp)) AS session_duration\n    FROM events\n    WHERE event = 'page_viewed'\n        AND timestamp >= now() - interval 3 day\n        AND (person_id IN COHORT 181727 OR person_id IN COHORT 181725)\n    GROUP BY day, $session_id, person_id, cohort_id\n)\nGROUP BY cohort_id, day\nORDER BY cohort_id, day DESC",
                        },
                        visible: false,
                    },
                    {
                        content:
                            'The query is now updated to return results for both cohort 181727 and cohort 181725, grouped by cohort and day, with the cohort ID shown in the results. All other logic remains the same.',
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
            $ai_span_id: 'b12fab67-ced0-451d-8f60-9260ccd43398',
            $python_runtime: 'CPython',
            $ai_latency: 0.039714813232421875,
            $lib_version: '6.7.4',
            $ai_parent_id: '0893a10a-4cff-4277-908f-dbaf70d8c02b',
            $ai_trace_id: '0893a10a-4cff-4277-908f-dbaf70d8c02b',
            $os: 'Linux',
            $os_version: '12',
            $ip: '52.4.194.122',
            $lib_version__major: 6,
            $lib_version__minor: 7,
            $lib_version__patch: 4,
            num_keys_in_properties: 469,
            $group_1: 'https://us.posthog.com',
            $group_0: '0195658a-abe2-0000-4cda-4b4d999ef970',
            $group_2: '0195658a-abf5-0000-977f-da4270beff18',
        }
    ),
}
