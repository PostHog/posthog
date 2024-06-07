import { HogFunctionType } from '../../src/cdp/types'

/**
 * Hog functions are largely generated and built in the django service, making it tricky to test on this side.
 * As such we have a bunch of prebuilt examples here for usage in tests.
 */
export const HOG_EXAMPLES: Record<string, Pick<HogFunctionType, 'hog' | 'bytecode'>> = {
    simple_fetch: {
        hog: "fetch(inputs.url, {\n  'headers': inputs.headers,\n  'body': inputs.payload,\n  'method': inputs.method,\n  'payload': inputs.payload\n});",
        bytecode: [
            '_h',
            32,
            'headers',
            32,
            'headers',
            32,
            'inputs',
            1,
            2,
            32,
            'body',
            32,
            'payload',
            32,
            'inputs',
            1,
            2,
            32,
            'method',
            32,
            'method',
            32,
            'inputs',
            1,
            2,
            32,
            'payload',
            32,
            'payload',
            32,
            'inputs',
            1,
            2,
            42,
            4,
            32,
            'url',
            32,
            'inputs',
            1,
            2,
            2,
            'fetch',
            2,
            35,
        ],
    },
}

export const HOG_INPUTS_EXAMPLES: Record<string, Pick<HogFunctionType, 'inputs' | 'inputs_schema'>> = {
    simple_fetch: {
        inputs_schema: [
            { key: 'url', type: 'string', label: 'Webhook URL', secret: false, required: true },
            { key: 'payload', type: 'json', label: 'JSON Payload', secret: false, required: true },
            {
                key: 'method',
                type: 'choice',
                label: 'HTTP Method',
                secret: false,
                choices: [
                    { label: 'POST', value: 'POST' },
                    { label: 'PUT', value: 'PUT' },
                    { label: 'PATCH', value: 'PATCH' },
                    { label: 'GET', value: 'GET' },
                ],
                required: true,
            },
            { key: 'headers', type: 'dictionary', label: 'Headers', secret: false, required: false },
        ],
        inputs: {
            url: {
                value: 'http://localhost:2080/0e02d917-563f-4050-9725-aad881b69937',
                bytecode: ['_h', 32, 'http://localhost:2080/0e02d917-563f-4050-9725-aad881b69937'],
            },
            method: { value: 'POST' },
            headers: {
                value: { version: 'v={event.properties.$lib_version}' },
                bytecode: {
                    version: ['_h', 32, '$lib_version', 32, 'properties', 32, 'event', 1, 3, 32, 'v=', 2, 'concat', 2],
                },
            },
            payload: {
                value: {
                    event: '{event}',
                    groups: '{groups}',
                    nested: { foo: '{event.url}' },
                    person: '{person}',
                    event_url: "{f'{event.url}-test'}",
                },
                bytecode: {
                    event: ['_h', 32, 'event', 1, 1],
                    groups: ['_h', 32, 'groups', 1, 1],
                    nested: { foo: ['_h', 32, 'url', 32, 'event', 1, 2] },
                    person: ['_h', 32, 'person', 1, 1],
                    event_url: ['_h', 32, '-test', 32, 'url', 32, 'event', 1, 2, 2, 'concat', 2],
                },
            },
        },
    },
}

export const HOG_FILTERS_EXAMPLES: Record<string, Pick<HogFunctionType, 'filters'>> = {
    no_filters: { filters: { events: [], actions: [], bytecode: ['_h', 29] } },
    pageview_or_autocapture_filter: {
        filters: {
            events: [
                {
                    id: '$pageview',
                    name: '$pageview',
                    type: 'events',
                    order: 0,
                    properties: [{ key: '$current_url', type: 'event', value: 'posthog', operator: 'icontains' }],
                },
                { id: '$autocapture', name: '$autocapture', type: 'events', order: 1 },
            ],
            actions: [],
            bytecode: [
                '_h',
                32,
                '$autocapture',
                32,
                'event',
                1,
                1,
                11,
                3,
                1,
                32,
                '%posthog%',
                32,
                '$current_url',
                32,
                'properties',
                1,
                2,
                18,
                32,
                '$pageview',
                32,
                'event',
                1,
                1,
                11,
                3,
                2,
                4,
                2,
            ],
        },
    },
}
