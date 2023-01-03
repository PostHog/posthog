import { ComponentMeta, ComponentStory } from '@storybook/react'

import { Trace } from 'lib/components/Performance/Traces/Trace'

export default {
    title: 'Components/Performance/Traces',
    component: Trace,
    parameters: { chromatic: { disableSnapshot: false } },
    argTypes: {
        // label: {
        //     defaultValue: 'Switch this!',
        // },
    },
} as ComponentMeta<typeof Trace>

const Template: ComponentStory<typeof Trace> = () => {
    return (
        <Trace
            timeToSeeSession={{
                type: 'session',
                data: {
                    session_id: '185643caa761ec3-0f14c53e8858b8-17525635-16a7f0-185643caa771155',
                    user_id: 1,
                    team_id: 1,
                    session_start: '2022-12-30T18:12:57.068000Z',
                    session_end: '2022-12-30T18:13:07.162000Z',
                    duration_ms: 10000,
                    team_events_last_month: 398,
                    events_count: 4,
                    interactions_count: 2,
                    total_interaction_time_to_see_data_ms: 4065,
                    frustrating_interactions_count: 0,
                    user: {
                        id: 1,
                        uuid: '01855e38-600e-0000-0145-619f033ffaa1',
                        distinct_id: 'UBhyEPC6HQEHgTFOeHCzQCyTbjPn7MzXbcVa9TPizmx',
                        first_name: 'asd',
                        email: 'paul@posthog.com',
                    },
                },
                children: [
                    {
                        type: 'interaction',
                        data: {
                            team_events_last_month: 398,
                            client_query_id: '',
                            primary_interaction_id: '771f61cc-a1ce-46ff-96fc-0e1692bbb6fb',
                            team_id: 1,
                            user_id: 1,
                            session_id: '185643caa761ec3-0f14c53e8858b8-17525635-16a7f0-185643caa771155',
                            timestamp: '2022-12-30T18:12:59.068000',
                            type: 'dashboard_load',
                            context: 'dashboard',
                            is_primary_interaction: true, //server returns 1?
                            time_to_see_data_ms: 2991,
                            status: '',
                            api_response_bytes: 3013,
                            current_url: 'http://127.0.0.1:8000/home',
                            api_url: '',
                            insight: '',
                            action: 'initial_load_full',
                            insights_fetched: 6,
                            insights_fetched_cached: 6,
                            min_last_refresh: '2022-12-30T13:14:46.492000',
                            max_last_refresh: '2022-12-30T13:14:47.246000',
                            is_frustrating: false, //server returned 0
                        },
                        children: [
                            {
                                type: 'event',
                                data: {
                                    team_events_last_month: 398,
                                    client_query_id: '',
                                    primary_interaction_id: '771f61cc-a1ce-46ff-96fc-0e1692bbb6fb',
                                    team_id: 1,
                                    user_id: 1,
                                    session_id: '185643caa761ec3-0f14c53e8858b8-17525635-16a7f0-185643caa771155',
                                    timestamp: '2022-12-30T18:12:59.506000',
                                    type: 'dashboard_load',
                                    context: 'dashboard',
                                    is_primary_interaction: false,
                                    time_to_see_data_ms: 2991,
                                    status: '',
                                    api_response_bytes: 3013,
                                    current_url: 'http://127.0.0.1:8000/home',
                                    api_url: '',
                                    insight: '',
                                    action: 'initial_load',
                                    insights_fetched: 6,
                                    insights_fetched_cached: 6,
                                    min_last_refresh: '2022-12-30T13:14:46.492000',
                                    max_last_refresh: '2022-12-30T13:14:47.246000',
                                    is_frustrating: false,
                                },
                                children: [],
                            },
                        ],
                    },
                    {
                        type: 'interaction',
                        data: {
                            team_events_last_month: 398,
                            client_query_id: '',
                            primary_interaction_id: '733ae81f-a70c-4611-857f-1baeda21780e',
                            team_id: 1,
                            user_id: 1,
                            session_id: '185643caa761ec3-0f14c53e8858b8-17525635-16a7f0-185643caa771155',
                            timestamp: '2022-12-30T18:13:07.132000',
                            type: 'dashboard_load',
                            context: 'dashboard',
                            is_primary_interaction: true,
                            time_to_see_data_ms: 5074,
                            status: '',
                            api_response_bytes: 3013,
                            current_url: 'http://127.0.0.1:8000/home',
                            api_url: '',
                            insight: '',
                            action: 'initial_load_full',
                            insights_fetched: 6,
                            insights_fetched_cached: 6,
                            min_last_refresh: '2022-12-30T13:14:46.492000',
                            max_last_refresh: '2022-12-30T13:14:47.246000',
                            is_frustrating: true,
                        },
                        children: [
                            {
                                type: 'event',
                                data: {
                                    team_events_last_month: 398,
                                    client_query_id: '',
                                    primary_interaction_id: '733ae81f-a70c-4611-857f-1baeda21780e',
                                    team_id: 1,
                                    user_id: 1,
                                    session_id: '185643caa761ec3-0f14c53e8858b8-17525635-16a7f0-185643caa771155',
                                    timestamp: '2022-12-30T18:13:07.162000',
                                    type: 'dashboard_load',
                                    context: 'dashboard',
                                    is_primary_interaction: false,
                                    time_to_see_data_ms: 5074,
                                    status: '',
                                    api_response_bytes: 3013,
                                    current_url: 'http://127.0.0.1:8000/home',
                                    api_url: '',
                                    insight: '',
                                    action: 'initial_load',
                                    insights_fetched: 6,
                                    insights_fetched_cached: 6,
                                    min_last_refresh: '2022-12-30T13:14:46.492000',
                                    max_last_refresh: '2022-12-30T13:14:47.246000',
                                    is_frustrating: true,
                                },
                                children: [],
                            },
                        ],
                    },
                ],
            }}
        />
    )
}

export const Basic = Template.bind({})
Basic.args = {}

// export const Overview = (): JSX.Element => {
//     return (
//         <div className="space-y-2">
//             <LemonSwitch label="Unchecked" checked={false} />
//             <LemonSwitch label="Checked" checked />
//
//             <LemonSwitch label="Bordered Unchecked" bordered />
//             <LemonSwitch label="Bordered Checked" checked bordered />
//
//             <LemonSwitch label="Bordered FullWidth" fullWidth bordered />
//             <LemonSwitch label="Bordered FullWidth icon" fullWidth bordered icon={<IconGlobeLock />} />
//             <LemonSwitch label="Bordered disabled" bordered disabled />
//             <LemonSwitch label="Bordered small" bordered size="small" />
//         </div>
//     )
// }
//
// export const Standalone = Template.bind({})
// Standalone.args = { label: undefined }
//
// export const Bordered = Template.bind({})
// Bordered.args = { bordered: true }
//
// export const Disabled = Template.bind({})
// Disabled.args = { disabled: true }
