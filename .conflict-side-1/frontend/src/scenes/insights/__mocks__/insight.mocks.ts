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
    next: 'https://app.posthog.com/api/projects/1/persons/retention/?insight=RETENTION&target_entity=%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%7D&returning_entity=%7B%22id%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22name%22%3A%22%24pageview%22%7D&period=Day&retention_type=retention_first_time&display=ActionsTable&properties=%5B%5D&selected_interval=2&offset=100',
}

export const samplePersonProperties = [
    { id: 1, name: 'location', count: 1 },
    { id: 2, name: 'role', count: 2 },
    { id: 3, name: 'height', count: 3 },
]
