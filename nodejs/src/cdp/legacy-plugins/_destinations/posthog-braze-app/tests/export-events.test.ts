import { RetryError } from '@posthog/plugin-scaffold'

import { BrazePluginMeta, onEvent } from '../index'

describe('Braze: export-events', () => {
    const fetchMock = jest.fn()

    beforeEach(() => {
        fetchMock.mockReset()
    })

    const mockResponse = (response: any, status: number = 200) => {
        fetchMock.mockResolvedValueOnce({
            status: status,
            json: () => Promise.resolve(response),
            ok: status >= 200 && status < 300,
        })
    }

    test('onEvent sends $set attributes and events to Braze', async () => {
        mockResponse({ message: 'success', attributes_processed: 1 })

        // Create a meta object that we can pass into the onEvent
        const meta = {
            config: {
                brazeEndpoint: 'US-03',
                apiKey: 'test-api-key',
                eventsToExport: 'account created',
                userPropertiesToExport: 'email,name',
                eventsToExportUserPropertiesFrom: 'account created',
            },
            global: {},
            logger: {
                error: jest.fn(),
                log: jest.fn(),
                warn: jest.fn(),
                debug: jest.fn(),
            },
            fetch: fetchMock as unknown,
        } as unknown as BrazePluginMeta

        await onEvent(
            {
                event: 'account created',
                timestamp: '2023-06-16T00:00:00.00Z',
                properties: {
                    $set: {
                        email: 'test@posthog',
                        name: 'Test User',
                    },
                    is_a_demo_user: true,
                },
                distinct_id: 'test',
                ip: '',
                team_id: 0,
                uuid: 'test-uuid',
                elements: [],
            },
            meta
        )

        expect(fetchMock.mock.calls.length).toEqual(1)
        expect(fetchMock.mock.calls[0][1]).toEqual({
            method: 'POST',
            headers: {
                Accept: 'application/json',
                Authorization: 'Bearer test-api-key',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                attributes: [
                    {
                        email: 'test@posthog',
                        name: 'Test User',
                        external_id: 'test',
                    },
                ],
                events: [
                    {
                        // NOTE: $set properties are filtered out
                        properties: {
                            is_a_demo_user: true,
                        },
                        external_id: 'test',
                        name: 'account created',
                        time: '2023-06-16T00:00:00.00Z',
                    },
                ],
            }),
            timeout: 5000,
        })
    })

    test('onEvent user properties not sent on empty userPropertiesToExport', async () => {
        mockResponse({ message: 'success', attributes_processed: 1 })

        // Create a meta object that we can pass into the onEvent
        const meta = {
            config: {
                brazeEndpoint: 'US-01',
                apiKey: 'test-api-key',
                eventsToExport: 'account created',
                eventsToExportUserPropertiesFrom: 'account created',
                userPropertiesToExport: '',
            },
            global: {},
            logger: {
                error: jest.fn(),
                log: jest.fn(),
                warn: jest.fn(),
                debug: jest.fn(),
            },
            fetch: fetchMock as unknown,
        } as unknown as BrazePluginMeta

        await onEvent(
            {
                event: 'account created',
                timestamp: '2023-06-16T00:00:00.00Z',
                properties: {
                    $set: {
                        email: 'test@posthog',
                        name: 'Test User',
                    },
                    is_a_demo_user: true,
                },
                distinct_id: 'test',
                ip: '',
                team_id: 0,
                uuid: 'test-uuid',
                elements: [],
            },
            meta
        )

        expect(fetchMock.mock.calls.length).toEqual(1)
        expect(fetchMock.mock.calls[0][1]).toEqual({
            method: 'POST',
            headers: {
                Accept: 'application/json',
                Authorization: 'Bearer test-api-key',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                attributes: [],
                events: [
                    {
                        properties: {
                            is_a_demo_user: true,
                        },
                        external_id: 'test',
                        name: 'account created',
                        time: '2023-06-16T00:00:00.00Z',
                    },
                ],
            }),
            timeout: 5000,
        })
    })

    test('onEvent user properties not sent on empty eventsToExportUserPropertiesFrom', async () => {
        mockResponse({ message: 'success', attributes_processed: 1 })

        // Create a meta object that we can pass into the onEvent
        const meta = {
            config: {
                brazeEndpoint: 'US-01',
                apiKey: 'test-api-key',
                eventsToExport: 'account created',
                userPropertiesToExport: 'email,name',
                eventsToExportUserPropertiesFrom: '',
            },
            global: {},
            logger: {
                error: jest.fn(),
                log: jest.fn(),
                warn: jest.fn(),
                debug: jest.fn(),
            },
            fetch: fetchMock as unknown,
        } as unknown as BrazePluginMeta

        await onEvent(
            {
                event: 'account created',
                timestamp: '2023-06-16T00:00:00.00Z',
                properties: {
                    $set: {
                        email: 'test@posthog',
                        name: 'Test User',
                    },
                    is_a_demo_user: true,
                },
                distinct_id: 'test',
                ip: '',
                team_id: 0,
                uuid: 'test-uuid',
                elements: [],
            },
            meta
        )

        expect(fetchMock.mock.calls.length).toEqual(1)
        expect(fetchMock.mock.calls[0][1]).toEqual({
            method: 'POST',
            headers: {
                Accept: 'application/json',
                Authorization: 'Bearer test-api-key',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                attributes: [],
                events: [
                    {
                        properties: {
                            is_a_demo_user: true,
                        },
                        external_id: 'test',
                        name: 'account created',
                        time: '2023-06-16T00:00:00.00Z',
                    },
                ],
            }),
            timeout: 5000,
        })
    })

    test('onEvent user properties are passed for $identify event even if $identify is not reported', async () => {
        mockResponse({ message: 'success', attributes_processed: 1 })

        // Create a meta object that we can pass into the onEvent
        const meta = {
            config: {
                brazeEndpoint: 'EU-01',
                apiKey: 'test-api-key',
                eventsToExport: 'account created',
                userPropertiesToExport: 'email',
                eventsToExportUserPropertiesFrom: 'account created,$identify',
            },
            global: {},
            logger: {
                error: jest.fn(),
                log: jest.fn(),
                warn: jest.fn(),
                debug: jest.fn(),
            },
            fetch: fetchMock as unknown,
        } as unknown as BrazePluginMeta

        await onEvent(
            {
                event: '$identify',
                timestamp: '2023-06-16T00:00:00.00Z',
                properties: {
                    $set: {
                        email: 'test@posthog',
                        name: 'Test User',
                    },
                    is_a_demo_user: true,
                },
                distinct_id: 'test',
                ip: '',
                team_id: 0,
                uuid: 'test-uuid',
                elements: [],
            },
            meta
        )

        expect(fetchMock.mock.calls.length).toEqual(1)
        expect(fetchMock.mock.calls[0][1]).toEqual({
            method: 'POST',
            headers: {
                Accept: 'application/json',
                Authorization: 'Bearer test-api-key',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                attributes: [
                    {
                        email: 'test@posthog',
                        external_id: 'test',
                    },
                ],
                events: [],
            }),
            timeout: 5000,
        })
    })

    test('onEvent user properties are not passed for non-whitelisted events', async () => {
        mockResponse({ message: 'success', attributes_processed: 1 })

        // Create a meta object that we can pass into the onEvent
        const meta = {
            config: {
                brazeEndpoint: 'US-01',
                apiKey: 'test-api-key',
                eventsToExport: 'account created',
                userPropertiesToExport: 'email',
                eventsToExportUserPropertiesFrom: 'account created',
            },
            global: {},
            logger: {
                error: jest.fn(),
                log: jest.fn(),
                warn: jest.fn(),
                debug: jest.fn(),
            },
            fetch: fetchMock as unknown,
        } as unknown as BrazePluginMeta

        await onEvent(
            {
                event: '$identify',
                timestamp: '2023-06-16T00:00:00.00Z',
                properties: {
                    $set: {
                        email: 'test@posthog',
                        name: 'Test User',
                    },
                    is_a_demo_user: true,
                },
                distinct_id: 'test',
                ip: '',
                team_id: 0,
                uuid: 'test-uuid',
                elements: [],
            },
            meta
        )

        expect(fetchMock.mock.calls.length).toEqual(0)
    })

    test('Braze API error (e.g. 400) are not retried', async () => {
        // NOTE: We only retry intermittent errors (e.g. 5xx), 4xx errors are most likely going to continue failing if retried

        const errorResponse = {
            errors: [
                {
                    type: "'external_id' or 'braze_id' or 'user_alias' is required",
                    input_array: 'attributes',
                    index: 0,
                },
            ],
        }

        mockResponse(errorResponse, 400)

        // Create a meta object that we can pass into the onEvent
        const meta = {
            config: {
                brazeEndpoint: 'US-02',
                apiKey: 'test-api-key',
                eventsToExport: 'account created',
                userPropertiesToExport: 'email',
                eventsToExportUserPropertiesFrom: 'account created,$identify',
            },
            global: {},
            logger: {
                error: jest.fn(),
                log: jest.fn(),
                warn: jest.fn(),
                debug: jest.fn(),
            },
            fetch: fetchMock as unknown,
        } as unknown as BrazePluginMeta

        await onEvent(
            {
                event: '$identify',
                timestamp: '2023-06-16T00:00:00.00Z',
                properties: {
                    $set: {
                        email: 'test@posthog',
                        name: 'Test User',
                    },
                    is_a_demo_user: true,
                },
                distinct_id: 'test',
                ip: '',
                team_id: 0,
                uuid: 'test-uuid',
                elements: [],
            },
            meta
        )

        expect(meta.logger.error).toHaveBeenCalledWith(
            'Braze API error (not retried): ',
            errorResponse,
            '/users/track',
            expect.anything(),
            expect.any(String)
        )
    })

    test('Braze offline error (500 response)', async () => {
        mockResponse({ message: 'error' }, 500)

        // Create a meta object that we can pass into the onEvent
        const meta = {
            config: {
                brazeEndpoint: 'US-02',
                apiKey: 'test-api-key',
                eventsToExport: 'account created',
                userPropertiesToExport: 'email',
                eventsToExportUserPropertiesFrom: 'account created,$identify',
            },
            global: {},
            logger: {
                error: jest.fn(),
                log: jest.fn(),
                warn: jest.fn(),
                debug: jest.fn(),
            },
            fetch: fetchMock as unknown,
        } as unknown as BrazePluginMeta

        try {
            await onEvent(
                {
                    event: '$identify',
                    timestamp: '2023-06-16T00:00:00.00Z',
                    properties: {
                        $set: {
                            email: 'test@posthog',
                            name: 'Test User',
                        },
                        is_a_demo_user: true,
                    },
                    distinct_id: 'test',
                    ip: '',
                    team_id: 0,
                    uuid: 'test-uuid',
                    elements: [],
                },
                meta
            )
            throw new Error('Should not reach here')
        } catch (e) {
            expect(e instanceof RetryError).toBeTruthy()
            expect(e.message).toMatch('Service is down, retry later. Request ID: ')
        }
    })

    test('Braze offline error (network error)', async () => {
        fetchMock.mockImplementationOnce(() => {
            throw new Error('Failed to connect')
        })

        // Create a meta object that we can pass into the onEvent
        const meta = {
            config: {
                brazeEndpoint: 'US-02',
                apiKey: 'test-api-key',
                eventsToExport: 'account created',
                userPropertiesToExport: 'email',
                eventsToExportUserPropertiesFrom: 'account created,$identify',
            },
            global: {},
            logger: {
                error: jest.fn(),
                log: jest.fn(),
                warn: jest.fn(),
                debug: jest.fn(),
            },
            fetch: fetchMock as unknown,
        } as unknown as BrazePluginMeta

        try {
            await onEvent(
                {
                    event: '$identify',
                    timestamp: '2023-06-16T00:00:00.00Z',
                    properties: {
                        $set: {
                            email: 'test@posthog',
                            name: 'Test User',
                        },
                        is_a_demo_user: true,
                    },
                    distinct_id: 'test',
                    ip: '',
                    team_id: 0,
                    uuid: 'test-uuid',
                    elements: [],
                },
                meta
            )
            throw new Error('Should not reach here')
        } catch (e) {
            expect(e instanceof RetryError).toBeTruthy()
            expect(e.message).toMatch('Fetch failed, retrying.')
        }
    })
})
