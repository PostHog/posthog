import { ComponentMeta, ComponentStory } from '@storybook/react'

import { Trace } from 'lib/components/Performance/Traces/Trace'
import { TimeToSeeSessionNode } from '~/queries/nodes/TimeToSeeData/types'

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
    const mockData: TimeToSeeSessionNode = {
        type: 'session',
        data: {
            session_id: '1855e890e3e1bb0-0bc9379ef5bb36-17525635-384000-1855e890e3f2b20',
            user_id: 1,
            team_id: 1,
            session_start: '2022-12-29T15:42:07.340000Z',
            session_end: '2022-12-29T15:42:16.328000Z',
            duration_ms: 9000,
            team_events_last_month: 132,
            events_count: 4,
            interactions_count: 3,
            total_interaction_time_to_see_data_ms: 811,
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
                    team_events_last_month: 132,
                    query_id: '7b16f80f-9560-461d-bd07-f9b6c1be9a14',
                    primary_interaction_id: '7b16f80f-9560-461d-bd07-f9b6c1be9a14',
                    team_id: 1,
                    user_id: 1,
                    session_id: '1855e890e3e1bb0-0bc9379ef5bb36-17525635-384000-1855e890e3f2b20',
                    timestamp: '2022-12-29T15:42:07.340000',
                    type: 'insight_load',
                    context: 'insight',
                    is_primary_interaction: 1,
                    time_to_see_data_ms: 254,
                    status: 'success',
                    api_response_bytes: 496,
                    current_url: 'http://127.0.0.1:8000/insights/DVgGKop7',
                    api_url: 'api/projects/1/insights/21/?refresh=true',
                    insight: 'TRENDS',
                    action: '',
                    insights_fetched: 1,
                    insights_fetched_cached: 0,
                    min_last_refresh: '1970-01-01T00:00:00',
                    max_last_refresh: '1970-01-01T00:00:00',
                    is_frustrating: 0,
                },
                children: [],
            },
            {
                type: 'interaction',
                data: {
                    team_events_last_month: 132,
                    query_id: '118d6976-d536-497e-a1dd-bedc34a8a127',
                    primary_interaction_id: '118d6976-d536-497e-a1dd-bedc34a8a127',
                    team_id: 1,
                    user_id: 1,
                    session_id: '1855e890e3e1bb0-0bc9379ef5bb36-17525635-384000-1855e890e3f2b20',
                    timestamp: '2022-12-29T15:42:11.390000',
                    type: 'insight_load',
                    context: 'insight',
                    is_primary_interaction: 1,
                    time_to_see_data_ms: 219,
                    status: 'success',
                    api_response_bytes: 105,
                    current_url: 'http://127.0.0.1:8000/insights/DVgGKop7',
                    api_url:
                        'api/projects/1/insights/trend/?insight=TRENDS&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22math%22%3A%22dau%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%5D&display=WorldMap&interval=day&breakdown=%24geoip_country_code&date_from=-90d&breakdown_type=person&filter_test_accounts=true&properties=%5B%5D&client_query_id=118d6976-d536-497e-a1dd-bedc34a8a127&session_id=1855e890e3e1bb0-0bc9379ef5bb36-17525635-384000-1855e890e3f2b20',
                    insight: 'TRENDS',
                    action: '',
                    insights_fetched: 1,
                    insights_fetched_cached: 0,
                    min_last_refresh: '1970-01-01T00:00:00',
                    max_last_refresh: '1970-01-01T00:00:00',
                    is_frustrating: 0,
                },
                children: [],
            },
            {
                type: 'interaction',
                data: {
                    team_events_last_month: 132,
                    query_id: '',
                    primary_interaction_id: 'fb7e71f1-dcd5-41a1-ac33-15c20ddada4a',
                    team_id: 1,
                    user_id: 1,
                    session_id: '1855e890e3e1bb0-0bc9379ef5bb36-17525635-384000-1855e890e3f2b20',
                    timestamp: '2022-12-29T15:42:16.327000',
                    type: 'dashboard_load',
                    context: 'dashboard',
                    is_primary_interaction: 1,
                    time_to_see_data_ms: 338,
                    status: '',
                    api_response_bytes: 3480,
                    current_url: 'http://127.0.0.1:8000/dashboard/1',
                    api_url: '',
                    insight: '',
                    action: 'initial_load_full',
                    insights_fetched: 6,
                    insights_fetched_cached: 6,
                    min_last_refresh: '2022-12-29T14:11:02.553000',
                    max_last_refresh: '2022-12-29T14:11:03.448000',
                    is_frustrating: 0,
                },
                children: [
                    {
                        type: 'event',
                        data: {
                            team_events_last_month: 132,
                            query_id: '',
                            primary_interaction_id: 'fb7e71f1-dcd5-41a1-ac33-15c20ddada4a',
                            team_id: 1,
                            user_id: 1,
                            session_id: '1855e890e3e1bb0-0bc9379ef5bb36-17525635-384000-1855e890e3f2b20',
                            timestamp: '2022-12-29T15:42:16.328000',
                            type: 'dashboard_load',
                            context: 'dashboard',
                            is_primary_interaction: 0,
                            time_to_see_data_ms: 338,
                            status: '',
                            api_response_bytes: 3480,
                            current_url: 'http://127.0.0.1:8000/dashboard/1',
                            api_url: '',
                            insight: '',
                            action: 'initial_load',
                            insights_fetched: 6,
                            insights_fetched_cached: 6,
                            min_last_refresh: '2022-12-29T14:11:02.553000',
                            max_last_refresh: '2022-12-29T14:11:03.448000',
                            is_frustrating: 0,
                        },
                        children: [
                            {
                                type: 'query',
                                data: {
                                    host: 'ch1',
                                    timestamp: '2022-12-29T15:42:11',
                                    query_duration_ms: 11,
                                    read_rows: 225,
                                    read_bytes: 944918,
                                    result_rows: 1,
                                    result_bytes: 159,
                                    memory_usage: 945727,
                                    is_initial_query: 1,
                                    exception_code: 0,
                                    team_id: 1,
                                    team_events_last_month: 132,
                                    user_id: 1,
                                    session_id: '1855e890e3e1bb0-0bc9379ef5bb36-17525635-384000-1855e890e3f2b20',
                                    kind: 'request',
                                    query_type: 'get_breakdown_prop_values',
                                    client_query_id: '118d6976-d536-497e-a1dd-bedc34a8a127',
                                    id: '/api/projects/1/insights/trend/',
                                    route_id: 'api/projects/(?P<parent_lookup_team_id>[^/.]+)/insights/trend/?$',
                                    query_time_range_days: 91,
                                    has_joins: 0,
                                    has_json_operations: 1,
                                    filter_by_type: ['event'],
                                    breakdown_by: ['person'],
                                    entity_math: ['dau'],
                                    filter: '{"breakdown":"$geoip_country_code","breakdown_attribution_type":"first_touch","breakdown_normalize_url":false,"breakdown_type":"person","date_from":"-90d","display":"WorldMap","events":[{"id":"$pageview","type":"events","order":0,"name":"$pageview","custom_name":null,"math":"dau","math_property":null,"math_group_type_index":null,"properties":{}}],"insight":"TRENDS","interval":"day","properties":{"type":"AND","values":[{"key":"$host","operator":"is_not","type":"event","value":["localhost:8000","localhost:5000","127.0.0.1:8000","127.0.0.1:3000","localhost:3000"]}]},"smoothing_intervals":1}',
                                    tables: ['default.events', 'default.sharded_events'],
                                    columns: [
                                        'default.events.event',
                                        'default.events.person_id',
                                        'default.events.person_properties',
                                        'default.events.properties',
                                        'default.events.team_id',
                                        'default.events.timestamp',
                                        'default.sharded_events.event',
                                        'default.sharded_events.person_id',
                                        'default.sharded_events.person_properties',
                                        'default.sharded_events.properties',
                                        'default.sharded_events.team_id',
                                        'default.sharded_events.timestamp',
                                    ],
                                    query: "/* user_id:1 request:_api_projects_1_insights_trend_ */ \nSELECT groupArray(value) FROM (\n    SELECT\n        replaceRegexpAll(JSONExtractRaw(person_properties, '$geoip_country_code'), '^\"|\"$', '') AS value,\n        count(*) as count\n    FROM events e\n\n\n\n    WHERE\n        team_id = 1 AND event = '$pageview' AND toDateTime(timestamp, 'UTC') >= toDateTime('2022-09-30 00:00:00', 'UTC') AND toDateTime(timestamp, 'UTC') <= toDateTime('2022-12-29 23:59:59', 'UTC') AND (   NOT has(['localhost:8000', 'localhost:5000', '127.0.0.1:8000', '127.0.0.1:3000', 'localhost:3000'], replaceRegexpAll(JSONExtractRaw(e.properties, '$host'), '^\"|\"$', ''))) AND e.person_id != toUUIDOrZero('')\n    GROUP BY value\n    ORDER BY count DESC, value DESC\n    LIMIT 300 OFFSET 0\n)\n",
                                    log_comment:
                                        '{"user_id":1,"kind":"request","id":"/api/projects/1/insights/trend/","route_id":"api/projects/(?P<parent_lookup_team_id>[^/.]+)/insights/trend/?$","client_query_id":"118d6976-d536-497e-a1dd-bedc34a8a127","session_id":"1855e890e3e1bb0-0bc9379ef5bb36-17525635-384000-1855e890e3f2b20","container_hostname":"unknown","team_id":1,"cache_key":"cache_479f200a859d4efb95af62fb844b5a64","person_on_events_enabled":true,"query_type":"get_breakdown_prop_values","has_joins":false,"has_json_operations":true,"filter":{"breakdown":"$geoip_country_code","breakdown_attribution_type":"first_touch","breakdown_normalize_url":false,"breakdown_type":"person","date_from":"-90d","display":"WorldMap","events":[{"id":"$pageview","type":"events","order":0,"name":"$pageview","custom_name":null,"math":"dau","math_property":null,"math_group_type_index":null,"properties":{}}],"insight":"TRENDS","interval":"day","properties":{"type":"AND","values":[{"key":"$host","operator":"is_not","type":"event","value":["localhost:8000","localhost:5000","127.0.0.1:8000","127.0.0.1:3000","localhost:3000"]}]},"smoothing_intervals":1},"breakdown_by":["person"],"entity_math":["dau"],"filter_by_type":["event"],"query_time_range_days":91,"workload":"Workload.ONLINE"}',
                                    is_frustrating: 0,
                                },
                                children: [],
                            },
                            {
                                type: 'query',
                                data: {
                                    host: 'ch1',
                                    timestamp: '2022-12-29T15:42:11',
                                    query_duration_ms: 0,
                                    read_rows: 0,
                                    read_bytes: 0,
                                    result_rows: 0,
                                    result_bytes: 0,
                                    memory_usage: 5048,
                                    is_initial_query: 1,
                                    exception_code: 0,
                                    team_id: 1,
                                    team_events_last_month: 132,
                                    user_id: 1,
                                    session_id: '1855e890e3e1bb0-0bc9379ef5bb36-17525635-384000-1855e890e3f2b20',
                                    kind: 'request',
                                    query_type: 'trends_breakdown',
                                    client_query_id: '118d6976-d536-497e-a1dd-bedc34a8a127',
                                    id: '/api/projects/1/insights/trend/',
                                    route_id: 'api/projects/(?P<parent_lookup_team_id>[^/.]+)/insights/trend/?$',
                                    query_time_range_days: 91,
                                    has_joins: 0,
                                    has_json_operations: 0,
                                    filter_by_type: ['event'],
                                    breakdown_by: ['person'],
                                    entity_math: ['dau'],
                                    filter: '{"breakdown":"$geoip_country_code","breakdown_attribution_type":"first_touch","breakdown_normalize_url":false,"breakdown_type":"person","date_from":"-90d","display":"WorldMap","events":[{"id":"$pageview","type":"events","order":0,"name":"$pageview","custom_name":null,"math":"dau","math_property":null,"math_group_type_index":null,"properties":{}}],"insight":"TRENDS","interval":"day","properties":{"type":"AND","values":[{"key":"$host","operator":"is_not","type":"event","value":["localhost:8000","localhost:5000","127.0.0.1:8000","127.0.0.1:3000","localhost:3000"]}]},"smoothing_intervals":1}',
                                    tables: ['system.one'],
                                    columns: ['system.one.dummy'],
                                    query: "/* user_id:1 request:_api_projects_1_insights_trend_ */ SELECT [now()] AS date, [0] AS data, '' AS breakdown_value LIMIT 0",
                                    log_comment:
                                        '{"user_id":1,"kind":"request","id":"/api/projects/1/insights/trend/","route_id":"api/projects/(?P<parent_lookup_team_id>[^/.]+)/insights/trend/?$","client_query_id":"118d6976-d536-497e-a1dd-bedc34a8a127","session_id":"1855e890e3e1bb0-0bc9379ef5bb36-17525635-384000-1855e890e3f2b20","container_hostname":"unknown","team_id":1,"cache_key":"cache_479f200a859d4efb95af62fb844b5a64","person_on_events_enabled":true,"query_type":"trends_breakdown","has_joins":false,"has_json_operations":false,"filter":{"breakdown":"$geoip_country_code","breakdown_attribution_type":"first_touch","breakdown_normalize_url":false,"breakdown_type":"person","date_from":"-90d","display":"WorldMap","events":[{"id":"$pageview","type":"events","order":0,"name":"$pageview","custom_name":null,"math":"dau","math_property":null,"math_group_type_index":null,"properties":{}}],"insight":"TRENDS","interval":"day","properties":{"type":"AND","values":[{"key":"$host","operator":"is_not","type":"event","value":["localhost:8000","localhost:5000","127.0.0.1:8000","127.0.0.1:3000","localhost:3000"]}]},"smoothing_intervals":1},"breakdown_by":["person"],"entity_math":["dau"],"filter_by_type":["event"],"query_time_range_days":91,"workload":"Workload.ONLINE"}',
                                    is_frustrating: 0,
                                },
                                children: [],
                            },
                        ],
                    },
                ],
            },
        ],
    }
    return <Trace timeToSeeSession={mockData} />
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
