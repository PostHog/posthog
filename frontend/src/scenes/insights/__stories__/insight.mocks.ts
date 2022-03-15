export const retention = {
    id: 6,
    short_id: '6C9YAfSl',
    name: 'Users by traffic source',
    derived_name: 'Retention of users based on doing Pageview for the first time and returning with the same event',
    filters: {
        period: 'Day',
        display: 'ActionsTable',
        insight: 'RETENTION',
        properties: [],
        target_entity: {
            id: '$pageview',
            name: '$pageview',
            type: 'events',
        },
        retention_type: 'retention_first_time',
        returning_entity: {
            id: '$pageview',
            name: '$pageview',
            type: 'events',
        },
        date_to: null,
        date_from: '-7d',
    },
    filters_hash: 'cache_137486649ad59a8c60a1fb4d75e16fb6',
    order: null,
    deleted: false,
    dashboard: 1,
    layouts: {
        sm: {
            h: 5,
            w: 6,
            x: 6,
            y: 10,
            minH: 5,
            minW: 3,
            moved: false,
            static: false,
        },
        xs: {
            h: 5,
            w: 1,
            x: 0,
            y: 25,
            minH: 5,
            minW: 3,
        },
    },
    color: null,
    last_refresh: '2022-03-14T21:19:50.310435Z',
    refreshing: false,
    result: [
        {
            values: [
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
            ],
            label: 'Day 0',
            date: '2022-03-04T00:00:00Z',
            people_url:
                '/api/person/retention/?breakdown_values=%5B0%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
        },
        {
            values: [
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
            ],
            label: 'Day 1',
            date: '2022-03-05T00:00:00Z',
            people_url:
                '/api/person/retention/?breakdown_values=%5B1%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
        },
        {
            values: [
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
            ],
            label: 'Day 2',
            date: '2022-03-06T00:00:00Z',
            people_url:
                '/api/person/retention/?breakdown_values=%5B2%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
        },
        {
            values: [
                {
                    count: 6783,
                    people: [],
                    people_url:
                        '/api/person/retention/?breakdown_values=%5B3%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
                },
                {
                    count: 31,
                    people: [],
                    people_url:
                        '/api/person/retention/?breakdown_values=%5B3%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&selected_interval=1&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
                },
                {
                    count: 20,
                    people: [],
                    people_url:
                        '/api/person/retention/?breakdown_values=%5B3%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&selected_interval=2&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
                },
                {
                    count: 7,
                    people: [],
                    people_url:
                        '/api/person/retention/?breakdown_values=%5B3%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&selected_interval=3&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
            ],
            label: 'Day 3',
            date: '2022-03-07T00:00:00Z',
            people_url:
                '/api/person/retention/?breakdown_values=%5B3%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
        },
        {
            values: [
                {
                    count: 10222,
                    people: [],
                    people_url:
                        '/api/person/retention/?breakdown_values=%5B4%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
                },
                {
                    count: 32,
                    people: [],
                    people_url:
                        '/api/person/retention/?breakdown_values=%5B4%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&selected_interval=1&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
                },
                {
                    count: 11,
                    people: [],
                    people_url:
                        '/api/person/retention/?breakdown_values=%5B4%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&selected_interval=2&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
                },
                {
                    count: 2,
                    people: [],
                    people_url:
                        '/api/person/retention/?breakdown_values=%5B4%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&selected_interval=3&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
            ],
            label: 'Day 4',
            date: '2022-03-08T00:00:00Z',
            people_url:
                '/api/person/retention/?breakdown_values=%5B4%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
        },
        {
            values: [
                {
                    count: 6590,
                    people: [],
                    people_url:
                        '/api/person/retention/?breakdown_values=%5B5%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
                },
                {
                    count: 8,
                    people: [],
                    people_url:
                        '/api/person/retention/?breakdown_values=%5B5%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&selected_interval=1&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
            ],
            label: 'Day 5',
            date: '2022-03-09T00:00:00Z',
            people_url:
                '/api/person/retention/?breakdown_values=%5B5%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
        },
        {
            values: [
                {
                    count: 2177,
                    people: [],
                    people_url:
                        '/api/person/retention/?breakdown_values=%5B6%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
                },
                {
                    count: 3,
                    people: [],
                    people_url:
                        '/api/person/retention/?breakdown_values=%5B6%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&selected_interval=1&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
            ],
            label: 'Day 6',
            date: '2022-03-10T00:00:00Z',
            people_url:
                '/api/person/retention/?breakdown_values=%5B6%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
        },
        {
            values: [
                {
                    count: 1066,
                    people: [],
                    people_url:
                        '/api/person/retention/?breakdown_values=%5B7%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 1,
                    people: [],
                    people_url:
                        '/api/person/retention/?breakdown_values=%5B7%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&selected_interval=3&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
                },
            ],
            label: 'Day 7',
            date: '2022-03-11T00:00:00Z',
            people_url:
                '/api/person/retention/?breakdown_values=%5B7%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
        },
        {
            values: [
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
            ],
            label: 'Day 8',
            date: '2022-03-12T00:00:00Z',
            people_url:
                '/api/person/retention/?breakdown_values=%5B8%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
        },
        {
            values: [
                {
                    count: 0,
                    people: [],
                },
                {
                    count: 0,
                    people: [],
                },
            ],
            label: 'Day 9',
            date: '2022-03-13T00:00:00Z',
            people_url:
                '/api/person/retention/?breakdown_values=%5B9%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
        },
        {
            values: [
                {
                    count: 53,
                    people: [],
                    people_url:
                        '/api/person/retention/?breakdown_values=%5B10%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
                },
            ],
            label: 'Day 10',
            date: '2022-03-14T00:00:00Z',
            people_url:
                '/api/person/retention/?breakdown_values=%5B10%5D&date_from=-7d&display=ActionsTable&insight=RETENTION&period=Day&retention_type=retention_first_time&returning_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&target_entity=%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D&total_intervals=11',
        },
    ],
    created_at: '2022-03-11T13:03:32.436101Z',
    created_by: null,
    description: 'Shows a breakdown of where unique users came from when visiting your app.',
    updated_at: '2022-03-15T20:35:52.740186Z',
    tags: [],
    favorited: false,
    saved: true,
    last_modified_at: '2022-03-11T19:37:11.415831Z',
    last_modified_by: {
        id: 1,
        uuid: '017f7913-c1ee-0000-faff-0fe5ace3849a',
        distinct_id: 'Q1OD2NmnqqbqrLR45mYm2p1VNNbSO9DBFsMig90GWkK',
        first_name: 'Marius',
        email: 'marius@posthog.com',
    },
    is_sample: false,
    effective_restriction_level: 21,
    effective_privilege_level: 37,
}
