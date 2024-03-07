import { FunnelAPIResponse } from '~/types'

// 1. Add step "Pageview"
export const funnelResult: FunnelAPIResponse = {
    result: [
        {
            action_id: '$pageview',
            name: '$pageview',
            custom_name: null,
            order: 0,
            people: [],
            count: 291,
            type: 'events',
            average_conversion_time: null,
            median_conversion_time: null,
            converted_people_url:
                '/api/person/funnel/?breakdown_attribution_type=first_touch&breakdown_normalize_url=False&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step=1&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
            dropped_people_url: null,
        },
        {
            action_id: '$pageview',
            name: '$pageview',
            custom_name: null,
            order: 1,
            people: [],
            count: 134,
            type: 'events',
            average_conversion_time: 87098.67529697785,
            median_conversion_time: 208.75,
            converted_people_url:
                '/api/person/funnel/?breakdown_attribution_type=first_touch&breakdown_normalize_url=False&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step=2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
            dropped_people_url:
                '/api/person/funnel/?breakdown_attribution_type=first_touch&breakdown_normalize_url=False&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step=-2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
        },
    ],
    timezone: 'UTC',
    last_refresh: '2023-02-22T08:24:07.710763Z',
    is_cached: true,
}

// 1. Add step "Pageview"
// 2. Add breakdown "Browser"
export const funnelResultWithBreakdown: FunnelAPIResponse = {
    result: [
        [
            {
                action_id: '$pageview',
                name: '$pageview',
                custom_name: null,
                order: 0,
                people: [],
                count: 136,
                type: 'events',
                average_conversion_time: null,
                median_conversion_time: null,
                breakdown_value: ['Chrome'],
                converted_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Chrome%22%5D&funnel_step=1&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                dropped_people_url: null,
                breakdowns: ['Chrome'],
            },
            {
                action_id: '$pageview',
                name: '$pageview',
                custom_name: null,
                order: 1,
                people: [],
                count: 66,
                type: 'events',
                average_conversion_time: 73028.08440653938,
                median_conversion_time: 112.0,
                breakdown_value: ['Chrome'],
                converted_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Chrome%22%5D&funnel_step=2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                dropped_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Chrome%22%5D&funnel_step=-2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                breakdowns: ['Chrome'],
            },
        ],
        [
            {
                action_id: '$pageview',
                name: '$pageview',
                custom_name: null,
                order: 0,
                people: [],
                count: 12,
                type: 'events',
                average_conversion_time: null,
                median_conversion_time: null,
                breakdown_value: ['Safari'],
                converted_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Safari%22%5D&funnel_step=1&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                dropped_people_url: null,
                breakdowns: ['Safari'],
            },
            {
                action_id: '$pageview',
                name: '$pageview',
                custom_name: null,
                order: 1,
                people: [],
                count: 6,
                type: 'events',
                average_conversion_time: 132776.4872685185,
                median_conversion_time: 62513.5,
                breakdown_value: ['Safari'],
                converted_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Safari%22%5D&funnel_step=2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                dropped_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Safari%22%5D&funnel_step=-2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                breakdowns: ['Safari'],
            },
        ],
        [
            {
                action_id: '$pageview',
                name: '$pageview',
                custom_name: null,
                order: 0,
                people: [],
                count: 53,
                type: 'events',
                average_conversion_time: null,
                median_conversion_time: null,
                breakdown_value: ['Firefox'],
                converted_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Firefox%22%5D&funnel_step=1&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                dropped_people_url: null,
                breakdowns: ['Firefox'],
            },
            {
                action_id: '$pageview',
                name: '$pageview',
                custom_name: null,
                order: 1,
                people: [],
                count: 27,
                type: 'events',
                average_conversion_time: 68104.22259380294,
                median_conversion_time: 112.0,
                breakdown_value: ['Firefox'],
                converted_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Firefox%22%5D&funnel_step=2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                dropped_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Firefox%22%5D&funnel_step=-2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                breakdowns: ['Firefox'],
            },
        ],
    ],
    timezone: 'UTC',
    last_refresh: '2023-02-22T08:29:29.281842Z',
    is_cached: true,
}

// 1. Add step "Pageview"
// 2. Add breakdown "Browser"
// 3. Add breakdown "OS"
export const funnelResultWithMultiBreakdown: FunnelAPIResponse = {
    result: [
        [
            {
                action_id: '$pageview',
                name: '$pageview',
                custom_name: null,
                order: 0,
                people: [],
                count: 15,
                type: 'events',
                average_conversion_time: null,
                median_conversion_time: null,
                breakdown_value: ['Chrome', 'Linux'],
                converted_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%2C+%22%24os%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%2C+%7B%22property%22%3A+%22%24os%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Chrome%22%2C+%22Linux%22%5D&funnel_step=1&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                dropped_people_url: null,
                breakdowns: ['Chrome', 'Linux'],
            },
            {
                action_id: '$pageview',
                name: '$pageview',
                custom_name: null,
                order: 1,
                people: [],
                count: 8,
                type: 'events',
                average_conversion_time: 74799.17588141025,
                median_conversion_time: 18617.0,
                breakdown_value: ['Chrome', 'Linux'],
                converted_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%2C+%22%24os%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%2C+%7B%22property%22%3A+%22%24os%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Chrome%22%2C+%22Linux%22%5D&funnel_step=2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                dropped_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%2C+%22%24os%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%2C+%7B%22property%22%3A+%22%24os%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Chrome%22%2C+%22Linux%22%5D&funnel_step=-2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                breakdowns: ['Chrome', 'Linux'],
            },
        ],
        [
            {
                action_id: '$pageview',
                name: '$pageview',
                custom_name: null,
                order: 0,
                people: [],
                count: 49,
                type: 'events',
                average_conversion_time: null,
                median_conversion_time: null,
                breakdown_value: ['Chrome', 'Mac OS X'],
                converted_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%2C+%22%24os%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%2C+%7B%22property%22%3A+%22%24os%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Chrome%22%2C+%22Mac+OS+X%22%5D&funnel_step=1&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                dropped_people_url: null,
                breakdowns: ['Chrome', 'Mac OS X'],
            },
            {
                action_id: '$pageview',
                name: '$pageview',
                custom_name: null,
                order: 1,
                people: [],
                count: 26,
                type: 'events',
                average_conversion_time: 81295.60927113237,
                median_conversion_time: 145.5,
                breakdown_value: ['Chrome', 'Mac OS X'],
                converted_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%2C+%22%24os%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%2C+%7B%22property%22%3A+%22%24os%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Chrome%22%2C+%22Mac+OS+X%22%5D&funnel_step=2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                dropped_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%2C+%22%24os%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%2C+%7B%22property%22%3A+%22%24os%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Chrome%22%2C+%22Mac+OS+X%22%5D&funnel_step=-2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                breakdowns: ['Chrome', 'Mac OS X'],
            },
        ],
        [
            {
                action_id: '$pageview',
                name: '$pageview',
                custom_name: null,
                order: 0,
                people: [],
                count: 5,
                type: 'events',
                average_conversion_time: null,
                median_conversion_time: null,
                breakdown_value: ['Internet Explorer', 'Windows'],
                converted_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%2C+%22%24os%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%2C+%7B%22property%22%3A+%22%24os%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Internet+Explorer%22%2C+%22Windows%22%5D&funnel_step=1&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                dropped_people_url: null,
                breakdowns: ['Internet Explorer', 'Windows'],
            },
            {
                action_id: '$pageview',
                name: '$pageview',
                custom_name: null,
                order: 1,
                people: [],
                count: 3,
                type: 'events',
                average_conversion_time: 105313.06349206349,
                median_conversion_time: 130763.0,
                breakdown_value: ['Internet Explorer', 'Windows'],
                converted_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%2C+%22%24os%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%2C+%7B%22property%22%3A+%22%24os%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Internet+Explorer%22%2C+%22Windows%22%5D&funnel_step=2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                dropped_people_url:
                    '/api/person/funnel/?breakdown=%5B%22%24browser%22%2C+%22%24os%22%5D&breakdowns=%5B%7B%22property%22%3A+%22%24browser%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%2C+%7B%22property%22%3A+%22%24os%22%2C+%22type%22%3A+%22event%22%2C+%22normalize_url%22%3A+false%7D%5D&breakdown_attribution_type=first_touch&breakdown_normalize_url=False&breakdown_type=event&date_from=2023-02-15T00%3A00%3A00%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&funnel_step_breakdown=%5B%22Internet+Explorer%22%2C+%22Windows%22%5D&funnel_step=-2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+2%7D%5D%7D&sample_factor=&smoothing_intervals=1',
                breakdowns: ['Internet Explorer', 'Windows'],
            },
        ],
    ],
    timezone: 'UTC',
    last_refresh: '2023-02-22T15:57:24.684263Z',
    is_cached: true,
}

// 1. Add step "Pageview"
// 2. Select graph type "Time to convert"
export const funnelResultTimeToConvert: FunnelAPIResponse = {
    result: {
        bins: [
            [4.0, 74],
            [73591.0, 24],
            [147178.0, 24],
            [220765.0, 10],
            [294352.0, 2],
            [367939.0, 1],
            [441526.0, 0],
        ],
        average_conversion_time: 86456.76,
    },
    timezone: 'UTC',
    last_refresh: '2023-02-22T17:32:24.245364Z',
    is_cached: false,
}

// 1. Add step "Pageview"
// 2. Select graph type "Time to convert"
// 3. Select time frame for which there is no data
export const funnelResultTimeToConvertWithoutConversions: FunnelAPIResponse = {
    result: {
        bins: [
            [0.0, 0],
            [1.0, 0],
        ],
        average_conversion_time: null,
    },
    timezone: 'UTC',
    last_refresh: '2023-03-03T12:02:22.618420Z',
    is_cached: false,
}

// 1. Add step "Pageview"
// 2. Select graph type "Trends"
export const funnelResultTrends = {
    result: [
        {
            count: 31,
            data: [74.12, 68.67, 71.05, 72.06, 69.33, 70.83, 72.37],
            days: ['2023-02-01', '2023-02-02', '2023-02-03', '2023-02-04', '2023-02-05', '2023-02-06', '2023-02-07'],
            labels: ['1-Feb-2023', '2-Feb-2023', '3-Feb-2023', '4-Feb-2023', '5-Feb-2023', '6-Feb-2023', '7-Feb-2023'],
        },
    ],
    timezone: 'UTC',
    last_refresh: '2023-03-03T18:55:57.840129Z',
    is_cached: false,
}

// 1. Add step "Pageview"
// 2. Add "Pageview" as exclusion step
export const funnelInvalidExclusionError = {
    type: 'validation_error',
    code: 'invalid_input',
    detail: "Exclusion steps cannot contain an event that's part of funnel steps.",
    attr: null,
}
