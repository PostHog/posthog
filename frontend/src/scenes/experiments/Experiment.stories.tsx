import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import {
    BreakdownAttributionType,
    ChartDisplayType,
    Experiment,
    FunnelConversionWindowTimeUnit,
    FunnelExperimentResults,
    FunnelsFilterType,
    FunnelVizType,
    InsightType,
    PropertyFilterType,
    PropertyOperator,
    SignificanceCode,
    TrendsExperimentResults,
} from '~/types'

const MOCK_FUNNEL_EXPERIMENT: Experiment = {
    id: 1,
    name: 'New sign-up flow',
    description:
        "We've rebuilt our sign-up page to offer a more personalized experience. Let's see if this version performs better with potential users.",
    start_date: '2022-12-10T08:06:27.027740Z',
    end_date: '2023-02-07T16:12:54.055481Z',
    feature_flag_key: 'signup-page-4.0',
    feature_flag: {
        id: 1,
        team_id: 1,
        name: 'New sign-up page',
        key: 'signup-page-4.0',
        active: false,
        deleted: false,
        ensure_experience_continuity: false,
        filters: {
            groups: [
                {
                    properties: [
                        {
                            key: 'company_name',
                            type: PropertyFilterType.Group,
                            value: 'awe',
                            operator: PropertyOperator.IContains,
                            group_type_index: 1,
                        },
                    ],
                    variant: null,
                    rollout_percentage: undefined,
                },
            ],
            payloads: {},
            multivariate: {
                variants: [
                    {
                        key: 'control',
                        rollout_percentage: 33,
                    },
                    {
                        key: 'test',
                        rollout_percentage: 33,
                    },
                    {
                        key: 'test_group_2',
                        rollout_percentage: 34,
                    },
                ],
            },
            aggregation_group_type_index: 1,
        },
    },
    parameters: {
        feature_flag_variants: [
            {
                key: 'control',
                rollout_percentage: 50,
            },
            {
                key: 'test',
                rollout_percentage: 50,
            },
        ],
        recommended_sample_size: 137,
        minimum_detectable_effect: 1,
    },
    secondary_metrics: [],
    filters: {
        events: [
            {
                id: '$pageview',
                name: '$pageview',
                type: 'events',
                order: 0,
                properties: [
                    {
                        key: '$current_url',
                        type: 'event',
                        value: 'https://hedgebox.net/signup/',
                        operator: 'exact',
                    },
                ],
            },
            {
                id: 'signed_up',
                name: 'signed_up',
                type: 'events',
                order: 1,
            },
        ],
        actions: [],
        insight: InsightType.FUNNELS,
        interval: 'day',
        filter_test_accounts: true,
    },
    archived: false,
    created_by: {
        id: 1,
        uuid: '01863799-062b-0000-8a61-b2842d5f8642',
        distinct_id: 'Sopz9Z4NMIfXGlJe6W1XF98GOqhHNui5J5eRe0tBGTE',
        first_name: 'Employee 427',
        email: 'test2@posthog.com',
    },
    created_at: '2022-12-10T07:06:27.027740Z',
    updated_at: '2023-02-09T19:13:57.137954Z',
}

const MOCK_TREND_EXPERIMENT: Experiment = {
    id: 2,
    name: 'aloha',
    start_date: '2023-02-11T10:37:17.634000Z',
    end_date: null,
    feature_flag_key: 'aloha',
    feature_flag: {
        id: 1,
        team_id: 1,
        name: 'Hellp everyone',
        key: 'aloha',
        active: false,
        deleted: false,
        ensure_experience_continuity: false,
        filters: {
            groups: [
                {
                    properties: [
                        {
                            key: 'company_name',
                            type: PropertyFilterType.Person,
                            value: 'awesome',
                            operator: PropertyOperator.IContains,
                        },
                    ],
                    variant: null,
                    rollout_percentage: undefined,
                },
            ],
            payloads: {},
            multivariate: {
                variants: [
                    {
                        key: 'control',
                        rollout_percentage: 50,
                    },
                    {
                        key: 'test',
                        rollout_percentage: 50,
                    },
                ],
            },
        },
    },
    parameters: {
        feature_flag_variants: [
            {
                key: 'control',
                rollout_percentage: 50,
            },
            {
                key: 'test',
                rollout_percentage: 50,
            },
        ],
        recommended_sample_size: 0,
        recommended_running_time: 28.3,
    },
    secondary_metrics: [],
    filters: {
        events: [
            {
                id: '$pageview',
                math: 'avg_count_per_actor',
                name: '$pageview',
                type: 'events',
                order: 0,
            },
        ],
        actions: [],
        date_to: '2023-05-19T23:59',
        insight: InsightType.TRENDS,
        interval: 'day',
        date_from: '2023-05-05T11:36',
        filter_test_accounts: false,
    },
    archived: false,
    created_by: {
        id: 1,
        uuid: '01881f35-b41a-0000-1d94-331938392cac',
        distinct_id: 'Xr1OY26ZsDh9ZbvA212ggq4l0Hf0dmEUjT33zvRPKrX',
        first_name: 'SS',
        email: 'test@posthog.com',
        is_email_verified: false,
    },
    created_at: '2022-03-15T21:31:00.192917Z',
    updated_at: '2022-03-15T21:31:00.192917Z',
}

const MOCK_TREND_EXPERIMENT_MANY_VARIANTS: Experiment = {
    id: 3,
    name: 'aloha',
    start_date: '2023-02-11T10:37:17.634000Z',
    end_date: null,
    feature_flag_key: 'aloha',
    feature_flag: {
        id: 1,
        team_id: 1,
        name: 'Hellp everyone',
        key: 'aloha',
        active: false,
        deleted: false,
        ensure_experience_continuity: false,
        filters: {
            groups: [
                {
                    properties: [
                        {
                            key: 'company_name',
                            type: PropertyFilterType.Person,
                            value: 'awesome',
                            operator: PropertyOperator.IContains,
                        },
                    ],
                    variant: null,
                    rollout_percentage: undefined,
                },
            ],
            payloads: {},
            multivariate: {
                variants: [
                    {
                        key: 'control',
                        rollout_percentage: 16,
                    },
                    {
                        key: 'test_1',
                        rollout_percentage: 16,
                    },
                    {
                        key: 'test_2',
                        rollout_percentage: 16,
                    },
                    {
                        key: 'test_3',
                        rollout_percentage: 16,
                    },
                    {
                        key: 'test_4',
                        rollout_percentage: 16,
                    },
                    {
                        key: 'test_5',
                        rollout_percentage: 20,
                    },
                ],
            },
        },
    },
    parameters: {
        feature_flag_variants: [
            {
                key: 'control',
                rollout_percentage: 16,
            },
            {
                key: 'test_1',
                rollout_percentage: 16,
            },
            {
                key: 'test_2',
                rollout_percentage: 16,
            },
            {
                key: 'test_3',
                rollout_percentage: 16,
            },
            {
                key: 'test_4',
                rollout_percentage: 16,
            },
            {
                key: 'test_5',
                rollout_percentage: 20,
            },
        ],
        recommended_sample_size: 0,
        recommended_running_time: 28.3,
    },
    secondary_metrics: [],
    filters: {
        events: [
            {
                id: '$pageview',
                math: 'avg_count_per_actor',
                name: '$pageview',
                type: 'events',
                order: 0,
            },
        ],
        actions: [],
        date_to: '2023-05-19T23:59',
        insight: InsightType.TRENDS,
        interval: 'day',
        date_from: '2023-05-05T11:36',
        filter_test_accounts: false,
    },
    archived: false,
    created_by: {
        id: 1,
        uuid: '01881f35-b41a-0000-1d94-331938392cac',
        distinct_id: 'Xr1OY26ZsDh9ZbvA212ggq4l0Hf0dmEUjT33zvRPKrX',
        first_name: 'SS',
        email: 'test@posthog.com',
        is_email_verified: false,
    },
    created_at: '2022-03-15T21:31:00.192917Z',
    updated_at: '2022-03-15T21:31:00.192917Z',
}

const MOCK_EXPERIMENT_RESULTS: FunnelExperimentResults = {
    result: {
        fakeInsightId: '123',
        insight: [
            [
                {
                    action_id: '$pageview',
                    name: '$pageview',
                    order: 0,
                    people: [],
                    count: 71,
                    type: 'events',
                    average_conversion_time: null,
                    median_conversion_time: null,
                    breakdown: ['test'],
                    breakdown_value: ['test'],
                    converted_people_url:
                        '/api/person/funnel/?breakdown=%5B%22%24feature%2Fsignup-page-4.0%22%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2022-12-10T08%3A06%3A27.027740%2B00%3A00&date_to=2023-02-07T16%3A12%3A54.055481%2B00%3A00&explicit_date=true&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24current_url%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%22https%3A%2F%2Fhedgebox.net%2Fsignup%2F%22%7D%5D%7D%7D%2C+%7B%22id%22%3A+%22signed_up%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22signed_up%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&filter_test_accounts=True&funnel_step_breakdown=%5B%22test%22%5D&funnel_step=1&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&smoothing_intervals=1',
                    dropped_people_url: null,
                },
                {
                    action_id: 'signed_up',
                    name: 'signed_up',
                    order: 1,
                    people: [],
                    count: 43,
                    type: 'events',
                    average_conversion_time: 53.04651162790697,
                    median_conversion_time: 53,
                    breakdown: ['test'],
                    breakdown_value: ['test'],
                    converted_people_url:
                        '/api/person/funnel/?breakdown=%5B%22%24feature%2Fsignup-page-4.0%22%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2022-12-10T08%3A06%3A27.027740%2B00%3A00&date_to=2023-02-07T16%3A12%3A54.055481%2B00%3A00&explicit_date=true&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24current_url%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%22https%3A%2F%2Fhedgebox.net%2Fsignup%2F%22%7D%5D%7D%7D%2C+%7B%22id%22%3A+%22signed_up%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22signed_up%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&filter_test_accounts=True&funnel_step_breakdown=%5B%22test%22%5D&funnel_step=2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&smoothing_intervals=1',
                    dropped_people_url:
                        '/api/person/funnel/?breakdown=%5B%22%24feature%2Fsignup-page-4.0%22%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2022-12-10T08%3A06%3A27.027740%2B00%3A00&date_to=2023-02-07T16%3A12%3A54.055481%2B00%3A00&explicit_date=true&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24current_url%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%22https%3A%2F%2Fhedgebox.net%2Fsignup%2F%22%7D%5D%7D%7D%2C+%7B%22id%22%3A+%22signed_up%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22signed_up%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&filter_test_accounts=True&funnel_step_breakdown=%5B%22test%22%5D&funnel_step=-2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&smoothing_intervals=1',
                },
            ],
            [
                {
                    action_id: '$pageview',
                    name: '$pageview',
                    custom_name: null,
                    order: 0,
                    people: [],
                    count: 69,
                    type: 'events',
                    average_conversion_time: null,
                    median_conversion_time: null,
                    breakdown: ['control'],
                    breakdown_value: ['control'],
                    converted_people_url:
                        '/api/person/funnel/?breakdown=%5B%22%24feature%2Fsignup-page-4.0%22%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2022-12-10T08%3A06%3A27.027740%2B00%3A00&date_to=2023-02-07T16%3A12%3A54.055481%2B00%3A00&explicit_date=true&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24current_url%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%22https%3A%2F%2Fhedgebox.net%2Fsignup%2F%22%7D%5D%7D%7D%2C+%7B%22id%22%3A+%22signed_up%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22signed_up%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&filter_test_accounts=True&funnel_step_breakdown=%5B%22control%22%5D&funnel_step=1&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&smoothing_intervals=1',
                    dropped_people_url: null,
                },
                {
                    action_id: 'signed_up',
                    name: 'signed_up',
                    custom_name: null,
                    order: 1,
                    people: [],
                    count: 31,
                    type: 'events',
                    average_conversion_time: 66.6774193548387,
                    median_conversion_time: 63,
                    breakdown: ['control'],
                    breakdown_value: ['control'],
                    converted_people_url:
                        '/api/person/funnel/?breakdown=%5B%22%24feature%2Fsignup-page-4.0%22%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2022-12-10T08%3A06%3A27.027740%2B00%3A00&date_to=2023-02-07T16%3A12%3A54.055481%2B00%3A00&explicit_date=true&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24current_url%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%22https%3A%2F%2Fhedgebox.net%2Fsignup%2F%22%7D%5D%7D%7D%2C+%7B%22id%22%3A+%22signed_up%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22signed_up%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&filter_test_accounts=True&funnel_step_breakdown=%5B%22control%22%5D&funnel_step=2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&smoothing_intervals=1',
                    dropped_people_url:
                        '/api/person/funnel/?breakdown=%5B%22%24feature%2Fsignup-page-4.0%22%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2022-12-10T08%3A06%3A27.027740%2B00%3A00&date_to=2023-02-07T16%3A12%3A54.055481%2B00%3A00&explicit_date=true&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24current_url%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%22https%3A%2F%2Fhedgebox.net%2Fsignup%2F%22%7D%5D%7D%7D%2C+%7B%22id%22%3A+%22signed_up%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22signed_up%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&filter_test_accounts=True&funnel_step_breakdown=%5B%22control%22%5D&funnel_step=-2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&smoothing_intervals=1',
                },
            ],
        ],
        probability: {
            control: 0.03264999999999996,
            test: 0.96735,
        },
        significant: false,
        filters: {
            breakdown: ['$feature/signup-page-4.0'],
            breakdown_attribution_type: BreakdownAttributionType.FirstTouch,
            breakdown_normalize_url: false,
            breakdown_type: 'event',
            date_from: '2022-12-10T08:06:27.027740+00:00',
            date_to: '2023-02-07T16:12:54.055481+00:00',
            explicit_date: 'true',
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
                    math_group_type_index: null,
                    properties: {
                        type: 'AND',
                        values: [
                            {
                                key: '$current_url',
                                operator: 'exact',
                                type: 'event',
                                value: 'https://hedgebox.net/signup/',
                            },
                        ],
                    },
                },
                {
                    id: 'signed_up',
                    type: 'events',
                    order: 1,
                    name: 'signed_up',
                    custom_name: null,
                    math: null,
                    math_property: null,
                    math_group_type_index: null,
                    properties: {},
                },
            ],
            filter_test_accounts: true,
            funnel_viz_type: FunnelVizType.Steps,
            funnel_window_interval: 14,
            funnel_window_interval_unit: FunnelConversionWindowTimeUnit.Day,
            insight: InsightType.FUNNELS,
            interval: 'day',
            limit: 100,
            smoothing_intervals: 1,
            sampling_factor: 0.1,
        } as FunnelsFilterType,
        significance_code: SignificanceCode.NotEnoughExposure,
        expected_loss: 1,
        variants: [
            {
                key: 'control',
                success_count: 31,
                failure_count: 38,
            },
            {
                key: 'test',
                success_count: 43,
                failure_count: 28,
            },
        ],
        credible_intervals: {
            control: [0.0126, 0.0526],
            test: [0.0526, 0.0826],
        },
    },
}

const MOCK_TREND_EXPERIMENT_RESULTS: TrendsExperimentResults = {
    result: {
        fakeInsightId: '1234',
        insight: [
            {
                action: {
                    id: '$pageview',
                    type: 'events',
                    order: 0,
                    name: '$pageview',
                    custom_name: null,
                    math: 'avg_count_per_actor',
                    math_property: undefined,
                    math_group_type_index: undefined,
                },
                aggregated_value: 0,
                label: '$pageview - test',
                count: 26,
                data: [2.5416666666666, 4.5416666666665, 3.5416666665, 1.666666666665, 8.366666665],
                labels: ['11-Feb-2023', '12-Feb-2023', '13-Feb-2023', '14-Feb-2023', '15-Feb-2023'],
                days: ['2023-02-11', '2023-02-12', '2023-02-13', '2023-02-14', '2023-02-15'],
                breakdown_value: 'test',
                persons_urls: [
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                ],
                filter: {
                    breakdown: '$feature/aloha',
                    breakdown_normalize_url: false,
                    breakdown_type: 'event',
                    date_from: '2023-02-11T10:37:17.634000Z',
                    date_to: '2023-02-16T10:37:17.634000Z',
                    explicit_date: 'true',
                    display: ChartDisplayType.ActionsLineGraph,
                    events: [
                        {
                            id: '$pageview',
                            type: 'events',
                            order: 0,
                            name: '$pageview',
                            custom_name: null,
                            math: 'avg_count_per_actor',
                            math_property: null,
                            math_group_type_index: null,
                            properties: {},
                        },
                    ],
                    insight: InsightType.TRENDS,
                    interval: 'day',
                    properties: [
                        {
                            key: '$feature/aloha',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                            value: ['control', 'test'],
                        },
                    ],
                    sampling_factor: undefined,
                    smoothing_intervals: 1,
                },
            },
            {
                action: {
                    id: '$pageview',
                    type: 'events',
                    order: 0,
                    name: '$pageview',
                    custom_name: null,
                    math: 'avg_count_per_actor',
                    math_property: undefined,
                    math_group_type_index: null,
                    properties: undefined,
                },
                aggregated_value: 0,
                label: '$pageview - control',
                count: 11.421053,
                data: [
                    2.4210526315789473, 1.4210526315789473, 3.4210526315789473, 0.4210526315789473, 3.4210526315789473,
                ],
                labels: ['11-Feb-2023', '12-Feb-2023', '13-Feb-2023', '14-Feb-2023', '15-Feb-2023'],
                days: ['2023-02-11', '2023-02-12', '2023-02-13', '2023-02-14', '2023-02-15'],
                breakdown_value: 'control',
                persons_urls: [
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                ],
                filter: {
                    breakdown: '$feature/aloha',
                    breakdown_normalize_url: false,
                    breakdown_type: 'event',
                    date_from: '2023-02-11T10:37:17.634000Z',
                    explicit_date: 'true',
                    display: ChartDisplayType.ActionsLineGraph,
                    events: [
                        {
                            id: '$pageview',
                            type: 'events',
                            order: 0,
                            name: '$pageview',
                            custom_name: null,
                            math: 'avg_count_per_actor',
                            math_property: null,
                            math_group_type_index: null,
                            properties: {},
                        },
                    ],
                    insight: InsightType.TRENDS,
                    interval: 'day',
                    properties: [
                        {
                            key: '$feature/aloha',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                            value: ['control', 'test'],
                        },
                    ],
                    sampling_factor: undefined,
                    smoothing_intervals: 1,
                },
            },
        ],
        probability: {
            control: 0.407580005,
            test: 0.59242,
        },
        significant: false,
        filters: {
            breakdown: '$feature/aloha',
            breakdown_normalize_url: false,
            breakdown_type: 'event',
            date_from: '2023-02-11T10:37:17.634000Z',
            explicit_date: 'true',
            display: ChartDisplayType.ActionsLineGraph,
            events: [
                {
                    id: '$pageview',
                    type: 'events',
                    order: 0,
                    name: '$pageview',
                    custom_name: null,
                    math: 'avg_count_per_actor',
                    math_property: null,
                    math_group_type_index: null,
                    properties: {},
                },
            ],
            insight: InsightType.TRENDS,
            interval: 'day',
            properties: [
                {
                    key: '$feature/aloha',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                    value: ['control', 'test'],
                },
            ],
            sampling_factor: undefined,
            smoothing_intervals: 1,
        },
        significance_code: SignificanceCode.NotEnoughExposure,
        p_value: 1,
        variants: [
            {
                key: 'control',
                count: 46,
                exposure: 1,
                absolute_exposure: 19,
            },
            {
                key: 'test',
                count: 61,
                exposure: 1.263157894736842,
                absolute_exposure: 24,
            },
        ],
        credible_intervals: {
            control: [1.5678, 3.8765],
            test: [1.2345, 3.4567],
        },
    },
    last_refresh: '2023-02-11T10:37:17.634000Z',
    is_cached: true,
}

const MOCK_TREND_EXPERIMENT_MANY_VARIANTS_RESULTS: TrendsExperimentResults = {
    result: {
        fakeInsightId: '12345',
        insight: [
            {
                action: {
                    id: '$pageview',
                    type: 'events',
                    order: 0,
                    name: '$pageview',
                    custom_name: null,
                    math: 'avg_count_per_actor',
                    math_property: undefined,
                    math_group_type_index: undefined,
                },
                aggregated_value: 0,
                label: '$pageview - test_1',
                count: 26,
                data: [2.5416666666666, 4.5416666666665, 3.5416666665, 1.666666666665, 8.366666665],
                labels: ['11-Feb-2023', '12-Feb-2023', '13-Feb-2023', '14-Feb-2023', '15-Feb-2023'],
                days: ['2023-02-11', '2023-02-12', '2023-02-13', '2023-02-14', '2023-02-15'],
                breakdown_value: 'test_1',
                persons_urls: [
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                ],
                filter: {
                    breakdown: '$feature/aloha',
                    breakdown_normalize_url: false,
                    breakdown_type: 'event',
                    date_from: '2023-02-11T10:37:17.634000Z',
                    date_to: '2023-02-16T10:37:17.634000Z',
                    explicit_date: 'true',
                    display: ChartDisplayType.ActionsLineGraph,
                    events: [
                        {
                            id: '$pageview',
                            type: 'events',
                            order: 0,
                            name: '$pageview',
                            custom_name: null,
                            math: 'avg_count_per_actor',
                            math_property: null,
                            math_group_type_index: null,
                            properties: {},
                        },
                    ],
                    insight: InsightType.TRENDS,
                    interval: 'day',
                    properties: [
                        {
                            key: '$feature/aloha',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                            value: ['control', 'test_1', 'test_2', 'test_3', 'test_4', 'test_5'],
                        },
                    ],
                    sampling_factor: undefined,
                    smoothing_intervals: 1,
                },
            },
            {
                action: {
                    id: '$pageview',
                    type: 'events',
                    order: 0,
                    name: '$pageview',
                    custom_name: null,
                    math: 'avg_count_per_actor',
                    math_property: undefined,
                    math_group_type_index: undefined,
                },
                aggregated_value: 0,
                label: '$pageview - test_2',
                count: 26,
                data: [3.5416666666666, 5.5416666666665, 4.5416666665, 2.666666666665, 9.366666665],
                labels: ['11-Feb-2023', '12-Feb-2023', '13-Feb-2023', '14-Feb-2023', '15-Feb-2023'],
                days: ['2023-02-11', '2023-02-12', '2023-02-13', '2023-02-14', '2023-02-15'],
                breakdown_value: 'test_2',
                persons_urls: [
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                ],
                filter: {
                    breakdown: '$feature/aloha',
                    breakdown_normalize_url: false,
                    breakdown_type: 'event',
                    date_from: '2023-02-11T10:37:17.634000Z',
                    date_to: '2023-02-16T10:37:17.634000Z',
                    explicit_date: 'true',
                    display: ChartDisplayType.ActionsLineGraph,
                    events: [
                        {
                            id: '$pageview',
                            type: 'events',
                            order: 0,
                            name: '$pageview',
                            custom_name: null,
                            math: 'avg_count_per_actor',
                            math_property: null,
                            math_group_type_index: null,
                            properties: {},
                        },
                    ],
                    insight: InsightType.TRENDS,
                    interval: 'day',
                    properties: [
                        {
                            key: '$feature/aloha',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                            value: ['control', 'test_1', 'test_2', 'test_3', 'test_4', 'test_5'],
                        },
                    ],
                    sampling_factor: undefined,
                    smoothing_intervals: 1,
                },
            },
            {
                action: {
                    id: '$pageview',
                    type: 'events',
                    order: 0,
                    name: '$pageview',
                    custom_name: null,
                    math: 'avg_count_per_actor',
                    math_property: undefined,
                    math_group_type_index: undefined,
                },
                aggregated_value: 0,
                label: '$pageview - test_3',
                count: 26,
                data: [1.8416666666666, 3.7416666666665, 2.2416666665, 1.166666666665, 8.866666665],
                labels: ['11-Feb-2023', '12-Feb-2023', '13-Feb-2023', '14-Feb-2023', '15-Feb-2023'],
                days: ['2023-02-11', '2023-02-12', '2023-02-13', '2023-02-14', '2023-02-15'],
                breakdown_value: 'test_3',
                persons_urls: [
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                ],
                filter: {
                    breakdown: '$feature/aloha',
                    breakdown_normalize_url: false,
                    breakdown_type: 'event',
                    date_from: '2023-02-11T10:37:17.634000Z',
                    date_to: '2023-02-16T10:37:17.634000Z',
                    explicit_date: 'true',
                    display: ChartDisplayType.ActionsLineGraph,
                    events: [
                        {
                            id: '$pageview',
                            type: 'events',
                            order: 0,
                            name: '$pageview',
                            custom_name: null,
                            math: 'avg_count_per_actor',
                            math_property: null,
                            math_group_type_index: null,
                            properties: {},
                        },
                    ],
                    insight: InsightType.TRENDS,
                    interval: 'day',
                    properties: [
                        {
                            key: '$feature/aloha',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                            value: ['control', 'test_1', 'test_2', 'test_3', 'test_4', 'test_5'],
                        },
                    ],
                    sampling_factor: undefined,
                    smoothing_intervals: 1,
                },
            },
            {
                action: {
                    id: '$pageview',
                    type: 'events',
                    order: 0,
                    name: '$pageview',
                    custom_name: null,
                    math: 'avg_count_per_actor',
                    math_property: undefined,
                    math_group_type_index: undefined,
                },
                aggregated_value: 0,
                label: '$pageview - test_4',
                count: 26,
                data: [4.5416666666666, 6.5416666666665, 5.5416666665, 3.666666666665, 10.366666665],
                labels: ['11-Feb-2023', '12-Feb-2023', '13-Feb-2023', '14-Feb-2023', '15-Feb-2023'],
                days: ['2023-02-11', '2023-02-12', '2023-02-13', '2023-02-14', '2023-02-15'],
                breakdown_value: 'test_4',
                persons_urls: [
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                ],
                filter: {
                    breakdown: '$feature/aloha',
                    breakdown_normalize_url: false,
                    breakdown_type: 'event',
                    date_from: '2023-02-11T10:37:17.634000Z',
                    date_to: '2023-02-16T10:37:17.634000Z',
                    explicit_date: 'true',
                    display: ChartDisplayType.ActionsLineGraph,
                    events: [
                        {
                            id: '$pageview',
                            type: 'events',
                            order: 0,
                            name: '$pageview',
                            custom_name: null,
                            math: 'avg_count_per_actor',
                            math_property: null,
                            math_group_type_index: null,
                            properties: {},
                        },
                    ],
                    insight: InsightType.TRENDS,
                    interval: 'day',
                    properties: [
                        {
                            key: '$feature/aloha',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                            value: ['control', 'test_1', 'test_2', 'test_3', 'test_4', 'test_5'],
                        },
                    ],
                    sampling_factor: undefined,
                    smoothing_intervals: 1,
                },
            },
            {
                action: {
                    id: '$pageview',
                    type: 'events',
                    order: 0,
                    name: '$pageview',
                    custom_name: null,
                    math: 'avg_count_per_actor',
                    math_property: undefined,
                    math_group_type_index: undefined,
                },
                aggregated_value: 0,
                label: '$pageview - test_5',
                count: 26,
                data: [0.5416666666666, 2.5416666666665, 1.5416666665, 0.666666666665, 5.366666665],
                labels: ['11-Feb-2023', '12-Feb-2023', '13-Feb-2023', '14-Feb-2023', '15-Feb-2023'],
                days: ['2023-02-11', '2023-02-12', '2023-02-13', '2023-02-14', '2023-02-15'],
                breakdown_value: 'test_5',
                persons_urls: [
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                ],
                filter: {
                    breakdown: '$feature/aloha',
                    breakdown_normalize_url: false,
                    breakdown_type: 'event',
                    date_from: '2023-02-11T10:37:17.634000Z',
                    date_to: '2023-02-16T10:37:17.634000Z',
                    explicit_date: 'true',
                    display: ChartDisplayType.ActionsLineGraph,
                    events: [
                        {
                            id: '$pageview',
                            type: 'events',
                            order: 0,
                            name: '$pageview',
                            custom_name: null,
                            math: 'avg_count_per_actor',
                            math_property: null,
                            math_group_type_index: null,
                            properties: {},
                        },
                    ],
                    insight: InsightType.TRENDS,
                    interval: 'day',
                    properties: [
                        {
                            key: '$feature/aloha',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                            value: ['control', 'test_1', 'test_2', 'test_3', 'test_4', 'test_5'],
                        },
                    ],
                    sampling_factor: undefined,
                    smoothing_intervals: 1,
                },
            },
            {
                action: {
                    id: '$pageview',
                    type: 'events',
                    order: 0,
                    name: '$pageview',
                    custom_name: null,
                    math: 'avg_count_per_actor',
                    math_property: undefined,
                    math_group_type_index: null,
                    properties: undefined,
                },
                aggregated_value: 0,
                label: '$pageview - control',
                count: 11.421053,
                data: [
                    2.8210526315789473, 2.4210526315789473, 1.4210526315789473, 1.4210526315789473, 2.4210526315789473,
                ],
                labels: ['11-Feb-2023', '12-Feb-2023', '13-Feb-2023', '14-Feb-2023', '15-Feb-2023'],
                days: ['2023-02-11', '2023-02-12', '2023-02-13', '2023-02-14', '2023-02-15'],
                breakdown_value: 'control',
                persons_urls: [
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                    {
                        url: 'api/projects/1/persons/trends/?breakdown=%24feature%2Faloha&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-05-19T00%3A00%3A00%2B00%3A00&explicit_date=true&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22avg_count_per_actor%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22%24feature%2Faloha%22%2C+%22operator%22%3A+%22exact%22%2C+%22type%22%3A+%22event%22%2C+%22value%22%3A+%5B%22control%22%2C+%22test%22%5D%7D%5D%7D&sampling_factor=&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&entity_math=avg_count_per_actor&date_to=2023-05-19T00%3A00%3A00%2B00%3A00&breakdown_value=control&cache_invalidation_key=iaDd6ork',
                    },
                ],
                filter: {
                    breakdown: '$feature/aloha',
                    breakdown_normalize_url: false,
                    breakdown_type: 'event',
                    date_from: '2023-02-11T10:37:17.634000Z',
                    explicit_date: 'true',
                    display: ChartDisplayType.ActionsLineGraph,
                    events: [
                        {
                            id: '$pageview',
                            type: 'events',
                            order: 0,
                            name: '$pageview',
                            custom_name: null,
                            math: 'avg_count_per_actor',
                            math_property: null,
                            math_group_type_index: null,
                            properties: {},
                        },
                    ],
                    insight: InsightType.TRENDS,
                    interval: 'day',
                    properties: [
                        {
                            key: '$feature/aloha',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                            value: ['control', 'test_1', 'test_2', 'test_3', 'test_4', 'test_5'],
                        },
                    ],
                    sampling_factor: undefined,
                    smoothing_intervals: 1,
                },
            },
        ],
        probability: {
            control: 0.407580005,
            test_1: 0.59242,
            test_2: 0.49242,
            test_3: 0.29242,
            test_4: 0.19242,
            test_5: 0.09242,
        },
        significant: false,
        filters: {
            breakdown: '$feature/aloha',
            breakdown_normalize_url: false,
            breakdown_type: 'event',
            date_from: '2023-02-11T10:37:17.634000Z',
            explicit_date: 'true',
            display: ChartDisplayType.ActionsLineGraph,
            events: [
                {
                    id: '$pageview',
                    type: 'events',
                    order: 0,
                    name: '$pageview',
                    custom_name: null,
                    math: 'avg_count_per_actor',
                    math_property: null,
                    math_group_type_index: null,
                    properties: {},
                },
            ],
            insight: InsightType.TRENDS,
            interval: 'day',
            properties: [
                {
                    key: '$feature/aloha',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                    value: ['control', 'test_1', 'test_2', 'test_3', 'test_4', 'test_5'],
                },
            ],
            sampling_factor: undefined,
            smoothing_intervals: 1,
        },
        significance_code: SignificanceCode.NotEnoughExposure,
        p_value: 1,
        variants: [
            {
                key: 'control',
                count: 46,
                exposure: 1,
                absolute_exposure: 19,
            },
            {
                key: 'test_1',
                count: 63,
                exposure: 1.263157894736842,
                absolute_exposure: 24,
            },
            {
                key: 'test_2',
                count: 21,
                exposure: 5.463157894736842,
                absolute_exposure: 34,
            },
            {
                key: 'test_3',
                count: 31,
                exposure: 4.463157894736842,
                absolute_exposure: 44,
            },
            {
                key: 'test_4',
                count: 41,
                exposure: 3.463157894736842,
                absolute_exposure: 54,
            },
            {
                key: 'test_5',
                count: 51,
                exposure: 2.463157894736842,
                absolute_exposure: 64,
            },
        ],
        credible_intervals: {
            control: [1.5678, 3.8765],
            test_1: [1.2345, 3.4567],
            test_2: [1.3345, 3.5567],
            test_3: [1.4345, 3.5567],
            test_4: [1.5345, 3.5567],
            test_5: [1.6345, 3.6567],
        },
    },
    last_refresh: '2023-02-11T10:37:17.634000Z',
    is_cached: true,
}

const meta: Meta = {
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-15', // To stabilize relative dates
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/experiments/': toPaginatedResponse([
                    MOCK_FUNNEL_EXPERIMENT,
                    MOCK_TREND_EXPERIMENT,
                    MOCK_TREND_EXPERIMENT_MANY_VARIANTS,
                ]),
                '/api/projects/:team_id/experiments/1/': MOCK_FUNNEL_EXPERIMENT,
                '/api/projects/:team_id/experiments/1/results/': MOCK_EXPERIMENT_RESULTS,
                '/api/projects/:team_id/experiments/2/': MOCK_TREND_EXPERIMENT,
                '/api/projects/:team_id/experiments/2/results/': MOCK_TREND_EXPERIMENT_RESULTS,
                '/api/projects/:team_id/experiments/3/': MOCK_TREND_EXPERIMENT_MANY_VARIANTS,
                '/api/projects/:team_id/experiments/3/results/': MOCK_TREND_EXPERIMENT_MANY_VARIANTS_RESULTS,
            },
        }),
    ],
}
export default meta
export const ExperimentsList: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.experiments())
    }, [])
    return <App />
}

export const CompleteFunnelExperiment: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.experiment(MOCK_FUNNEL_EXPERIMENT.id))
    }, [])
    return <App />
}
CompleteFunnelExperiment.parameters = {
    testOptions: {
        waitForSelector: '.card-secondary',
    },
}

export const RunningTrendExperiment: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.experiment(MOCK_TREND_EXPERIMENT.id))
    }, [])

    return <App />
}
RunningTrendExperiment.parameters = {
    testOptions: {
        waitForSelector: '.LemonBanner .LemonIcon',
    },
}

export const RunningTrendExperimentManyVariants: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.experiment(MOCK_TREND_EXPERIMENT_MANY_VARIANTS.id))
    }, [])

    return <App />
}
RunningTrendExperimentManyVariants.parameters = {
    testOptions: {
        waitForSelector: '.LemonBanner .LemonIcon',
    },
}

export const ExperimentNotFound: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.experiment('1200000'))
    }, [])
    return <App />
}
