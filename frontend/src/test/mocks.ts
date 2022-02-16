import { EventDefinition } from '~/types'

export const mockEventDefinitions: EventDefinition[] = [
    'event1',
    'test event',
    '$click',
    '$autocapture',
    'search',
    'other event',
    ...Array(50),
].map((name, index) => ({
    id: `uuid-${index}-foobar`,
    name: name || `misc-${index}-generated`,
    description: `${name || 'name generation'} is the best!`,
    query_usage_30_day: index * 3 + 1,
    volume_30_day: index * 13 + 2,
    tags: [],
}))

export const mockEventPropertyDefinition = {
    id: '017e8d9e-4241-0000-57ad-3a7237ffdb8e',
    name: '$active_feature_flags',
    description: '',
    tags: [],
    is_numerical: false,
    updated_at: '2022-01-24T21:32:38.359756Z',
    updated_by: null,
    volume_30_day: 2,
    query_usage_30_day: 1,
    is_event_property: true,
    property_type: undefined,
}

export const mockPersonProperty = {
    name: '$browser_version',
    count: 1,
}

export const mockGroup = {
    name: 'name',
    count: 3,
}

export const mockElement = {
    name: 'selector',
}

export const mockActionDefinition = {
    id: 3,
    name: 'Action',
    post_to_slack: false,
    slack_message_format: '',
    steps: [
        {
            id: 3,
            event: '$rageclick',
            tag_name: 'div',
            text: null,
            href: null,
            selector: null,
            url: 'test',
            name: 'Rage',
            url_matching: 'contains',
            properties: [],
        },
    ],
    created_at: '2022-01-24T21:32:38.360176Z',
    deleted: false,
    is_calculating: false,
    last_calculated_at: '2022-01-24T21:32:38.359756Z',
    team_id: 1,
    created_by: null,
}

export const mockCohort = {
    id: 1,
    name: 'Cohort',
    count: 1,
    groups: [{ id: 'a', name: 'Properties Group', count: 1, matchType: 'properties' }],
}

export const mockInsight = {
    id: 110,
    short_id: 'SvoU2bMC',
    name: null,
    filters: {
        breakdown: '$browser',
        breakdown_type: 'event',
        display: 'FunnelViz',
        events: [
            {
                id: '$pageview',
                type: 'events',
                order: 0,
                name: '$pageview',
                custom_name: null,
                math: null,
                math_property: null,
                properties: [],
            },
            {
                id: '$pageview',
                type: 'events',
                order: 1,
                name: '$pageview',
                custom_name: null,
                math: null,
                math_property: null,
                properties: [],
            },
            {
                id: '$pageview',
                type: 'events',
                order: 2,
                name: '$pageview',
                custom_name: null,
                math: null,
                math_property: null,
                properties: [],
            },
            {
                id: '$pageview',
                type: 'events',
                order: 3,
                name: '$pageview',
                custom_name: null,
                math: null,
                math_property: null,
                properties: [],
            },
        ],
        funnel_from_step: 0,
        funnel_to_step: 1,
        funnel_viz_type: 'steps',
        insight: 'FUNNELS',
        interval: 'day',
        layout: 'vertical',
    },
    filters_hash: 'cache_d0d88afd2fd8dd2af0b7f2e505588e99',
    order: null,
    deleted: false,
    dashboard: null,
    dive_dashboard: null,
    layouts: {},
    color: null,
    last_refresh: null,
    refreshing: false,
    result: null,
    created_at: '2021-09-22T18:22:20.036153Z',
    description: null,
    updated_at: '2021-09-22T19:03:49.322258Z',
    tags: [],
    favorited: false,
    saved: false,
    created_by: {
        id: 1,
        uuid: '017c0441-bcb2-0000-bccf-dfc24328c5f3',
        distinct_id: 'fM7b6ZFi8MOssbkDI55ot8tMY2hkzrHdRy1qERa6rCK',
        first_name: 'Alex',
        email: 'alex@posthog.com',
    },
}
