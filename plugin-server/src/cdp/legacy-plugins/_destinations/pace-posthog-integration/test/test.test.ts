import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { PaceMetaInput, onEvent } from '../index'

describe('Pace: onEvent', () => {
    const fetchMock = jest.fn()

    beforeEach(() => {
        fetchMock.mockReset()
    })

    const mockEvent: ProcessedPluginEvent = {
        uuid: '10000000-0000-4000-0000-000000000000',
        team_id: 1,
        distinct_id: '1234',
        event: 'my-event',
        timestamp: new Date().toISOString(),
        ip: '127.0.0.1',
        properties: {
            $ip: '127.0.0.1',
            $elements_chain: 'div:nth-child="1"nth-of-type="2"text="text"',
            foo: 'bar',
        },
    }

    test('all expected endpoint', async () => {
        // Create a meta object that we can pass into the onEvent
        const meta = {
            config: {
                api_key: 'i-am-an-api-key',
            },
            global: {},
            logger: {
                error: jest.fn(),
                log: jest.fn(),
                warn: jest.fn(),
                debug: jest.fn(),
            },
            fetch: fetchMock as unknown,
        } as unknown as PaceMetaInput

        await onEvent(mockEvent, meta)

        expect(fetchMock.mock.calls.length).toEqual(1)
        expect(fetchMock.mock.calls[0][1]).toEqual({
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'x-api-key': 'i-am-an-api-key',
            },
            body: JSON.stringify({
                data: {
                    uuid: '10000000-0000-4000-0000-000000000000',
                    team_id: 1,
                    distinct_id: '1234',
                    event: 'my-event',
                    timestamp: mockEvent.timestamp,
                    ip: '127.0.0.1',
                    properties: {
                        foo: 'bar',
                    },
                },
            }),
        })
    })
})
