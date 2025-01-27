import { Meta, PostHogEvent } from '@posthog/plugin-scaffold'

import plugin, { PaceMetaInput } from '../index'

const { composeWebhook } = plugin

const meta: Meta<PaceMetaInput> = {
    attachments: {},
    cache: {
        set: async () => {
            //
        },
        get: async () => {
            //
        },
        incr: async () => 1,
        expire: async () => true,
        lpush: async () => 1,
        lrange: async () => [],
        llen: async () => 1,
        lpop: async () => [],
        lrem: async () => 1,
    },
    config: {
        api_key: 'i-am-an-api-key',
    },
    geoip: {
        locate: async () => null,
    },
    global: {},
    jobs: {},
    metrics: {},
    storage: {
        set: async () => {
            //
        },
        get: async () => {
            //
        },
        del: async () => {
            //
        },
    },
    utils: {
        cursor: {
            init: async () => {
                //
            },
            increment: async () => 1,
        },
    },
}

const mockEvent: PostHogEvent = {
    uuid: '10000000-0000-4000-0000-000000000000',
    team_id: 1,
    distinct_id: '1234',
    event: 'my-event',
    timestamp: new Date(),
    properties: {
        $ip: '127.0.0.1',
        $elements_chain: 'div:nth-child="1"nth-of-type="2"text="text"',
        foo: 'bar',
    },
}

describe('plugin tests', () => {
    test('return expected webhook object', async () => {
        if (!composeWebhook) {
            throw new Error('Not implemented')
        }

        const webhook1 = composeWebhook(mockEvent, meta)
        expect(webhook1).toHaveProperty('url', 'https://data.production.paceapp.com/events')
        expect(webhook1?.headers).toMatchObject({
            'Content-Type': 'application/json',
            'x-api-key': 'i-am-an-api-key',
        })
        expect(webhook1).toHaveProperty('method', 'POST')
        expect(webhook1).toHaveProperty(
            'body',
            JSON.stringify({
                data: {
                    uuid: '10000000-0000-4000-0000-000000000000',
                    team_id: 1,
                    distinct_id: '1234',
                    event: 'my-event',
                    timestamp: mockEvent.timestamp,
                    properties: {
                        foo: 'bar',
                    },
                },
            })
        )
    })
})
