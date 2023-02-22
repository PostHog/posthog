import { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'
import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import {
    AvailableFeature,
    BreakdownAttributionType,
    Experiment,
    FunnelConversionWindowTimeUnit,
    FunnelExperimentResults,
    FunnelsFilterType,
    FunnelVizType,
    InsightType,
    SignificanceCode,
} from '~/types'
import { useAvailableFeatures } from '~/mocks/features'

const MOCK_FUNNEL_EXPERIMENT: Experiment = {
    id: 1,
    name: 'New sign-up flow',
    description:
        "We've rebuilt our sign-up page to offer a more personalized experience. Let's see if this version performs better with potential users.",
    start_date: '2022-12-10T08:06:27.027740Z',
    end_date: '2023-02-07T16:12:54.055481Z',
    feature_flag_key: 'signup-page-4.0',
    feature_flag: 2,
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

const MOCK_EXPERIMENT_RESULTS: FunnelExperimentResults = {
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
}

export default {
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
        viewMode: 'story',
        mockDate: '2023-02-15', // To stabilize relative dates
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/experiments/': toPaginatedResponse([MOCK_FUNNEL_EXPERIMENT]),
                '/api/projects/:team_id/experiments/:experiment_id/': MOCK_FUNNEL_EXPERIMENT,
                '/api/projects/:team_id/experiments/:experiment_id/results/': MOCK_EXPERIMENT_RESULTS,
            },
        }),
    ],
} as Meta

export function ExperimentsList(): JSX.Element {
    useAvailableFeatures([AvailableFeature.EXPERIMENTATION])
    useEffect(() => {
        router.actions.push(urls.experiments())
    }, [])
    return <App />
}

export function CompleteFunnelExperiment(): JSX.Element {
    useAvailableFeatures([AvailableFeature.EXPERIMENTATION])
    useEffect(() => {
        router.actions.push(urls.experiment(MOCK_FUNNEL_EXPERIMENT.id))
    }, [])
    return <App />
}

export function ExperimentsListPayGate(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.experiments())
    }, [])
    return <App />
}

export function ViewExperimentPayGate(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.experiment(MOCK_FUNNEL_EXPERIMENT.id))
    }, [])
    return <App />
}
