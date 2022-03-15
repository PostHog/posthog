export const sampleRetentionResponse = {
    result: [
        {
            values: [
                { count: 1086, people: [] },
                { count: 13, people: [] },
                { count: 15, people: [] },
                { count: 12, people: [] },
                { count: 10, people: [] },
                { count: 5, people: [] },
                { count: 3, people: [] },
                { count: 5, people: [] },
                { count: 4, people: [] },
                { count: 3, people: [] },
                { count: 6, people: [] },
            ],
            label: 'Day 0',
            date: '2021-11-13T00:00:00Z',
        },
        {
            values: [
                { count: 819, people: [] },
                { count: 21, people: [] },
                { count: 13, people: [] },
                { count: 13, people: [] },
                { count: 11, people: [] },
                { count: 6, people: [] },
                { count: 6, people: [] },
                { count: 4, people: [] },
                { count: 3, people: [] },
                { count: 3, people: [] },
            ],
            label: 'Day 1',
            date: '2021-11-14T00:00:00Z',
        },
        {
            values: [
                { count: 1245, people: [] },
                { count: 56, people: [] },
                { count: 37, people: [] },
                { count: 28, people: [] },
                { count: 8, people: [] },
                { count: 7, people: [] },
                { count: 7, people: [] },
                { count: 13, people: [] },
                { count: 6, people: [] },
            ],
            label: 'Day 2',
            date: '2021-11-15T00:00:00Z',
        },
        {
            values: [
                { count: 1369, people: [] },
                { count: 67, people: [] },
                { count: 28, people: [] },
                { count: 30, people: [] },
                { count: 7, people: [] },
                { count: 7, people: [] },
                { count: 29, people: [] },
                { count: 10, people: [] },
            ],
            label: 'Day 3',
            date: '2021-11-16T00:00:00Z',
        },
        {
            values: [
                { count: 1559, people: [] },
                { count: 64, people: [] },
                { count: 37, people: [] },
                { count: 14, people: [] },
                { count: 12, people: [] },
                { count: 28, people: [] },
                { count: 14, people: [] },
            ],
            label: 'Day 4',
            date: '2021-11-17T00:00:00Z',
        },
        {
            values: [
                { count: 1912, people: [] },
                { count: 96, people: [] },
                { count: 26, people: [] },
                { count: 18, people: [] },
                { count: 34, people: [] },
                { count: 20, people: [] },
            ],
            label: 'Day 5',
            date: '2021-11-18T00:00:00Z',
        },
        {
            values: [
                { count: 1595, people: [] },
                { count: 49, people: [] },
                { count: 21, people: [] },
                { count: 56, people: [] },
                { count: 24, people: [] },
            ],
            label: 'Day 6',
            date: '2021-11-19T00:00:00Z',
        },
        {
            values: [
                { count: 1013, people: [] },
                { count: 21, people: [] },
                { count: 18, people: [] },
                { count: 12, people: [] },
            ],
            label: 'Day 7',
            date: '2021-11-20T00:00:00Z',
        },
        {
            values: [
                { count: 721, people: [] },
                { count: 33, people: [] },
                { count: 16, people: [] },
            ],
            label: 'Day 8',
            date: '2021-11-21T00:00:00Z',
        },
        {
            values: [
                { count: 1183, people: [] },
                { count: 36, people: [] },
            ],
            label: 'Day 9',
            date: '2021-11-22T00:00:00Z',
        },
        { values: [{ count: 810, people: [] }], label: 'Day 10', date: '2021-11-23T00:00:00Z' },
    ],
    last_refresh: '2021-11-23T13:45:29.314009Z',
    is_cached: true,
}

export const sampleBreakdownRetentionResponse = {
    result: [
        {
            values: [
                { count: 1086, people: [] },
                { count: 13, people: [] },
                { count: 15, people: [] },
                { count: 12, people: [] },
                { count: 10, people: [] },
                { count: 5, people: [] },
                { count: 3, people: [] },
                { count: 5, people: [] },
                { count: 4, people: [] },
                { count: 3, people: [] },
                { count: 6, people: [] },
            ],
            label: 'Chrome::96',
        },
        {
            values: [
                { count: 819, people: [] },
                { count: 21, people: [] },
                { count: 13, people: [] },
                { count: 13, people: [] },
                { count: 11, people: [] },
                { count: 6, people: [] },
                { count: 6, people: [] },
                { count: 4, people: [] },
                { count: 3, people: [] },
                { count: 3, people: [] },
                { count: 2, people: [] },
            ],
            label: 'Safari::34',
        },
    ],
}

export const sampleRetentionPeopleResponse = {
    result: [
        {
            person: {
                id: 195158300,
                name: 'test_user@posthog.com',
                distinct_ids: ['1234'],
                properties: {
                    $os: 'Mac OS X',
                    email: 'test_user@posthog.com',
                },
                is_identified: true,
                created_at: '2021-11-15T15:23:54.099000Z',
                uuid: '017d27d1-173a-2345-9bb1-337a0bb07be3',
            },
            appearances: [true, true, true, true, true, true, true, true, true],
        },
        {
            person: {
                id: 194626019,
                name: 'test@posthog.com',
                distinct_ids: ['abc'],
                properties: {
                    $os: 'Mac OS X',
                    email: 'test@posthog.com',
                },
                is_identified: false,
                created_at: '2021-11-15T14:12:41.919000Z',
                uuid: '017d23f1-6326-3456-0c5c-af00affbd563',
            },
            appearances: [true, true, true, true, true, false, true, true, true],
        },
    ],
    next: 'https://app.posthog.com/api/person/retention/?insight=RETENTION&target_entity=%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%7D&returning_entity=%7B%22id%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22name%22%3A%22%24pageview%22%7D&period=Day&retention_type=retention_first_time&display=ActionsTable&properties=%5B%5D&selected_interval=2&offset=100',
}
