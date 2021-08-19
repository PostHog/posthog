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
}))
