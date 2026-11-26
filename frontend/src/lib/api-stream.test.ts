import * as fetchEventSourceModule from '@microsoft/fetch-event-source'

import api from 'lib/api'

import { createStreamConnection } from './api-stream'

describe('stream connections', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('does not reconnect when abort triggers a delayed stream error', () => {
        const streamSpy = jest.spyOn(api, 'stream').mockResolvedValue(undefined)
        const connection = createStreamConnection({
            url: new URL('https://example.com/events'),
            token: 'token',
            onMessage: jest.fn(),
        })
        const streamOptions = streamSpy.mock.calls[0][1]

        connection.abort()
        streamOptions.onError(new Error('aborted'))
        jest.runAllTimers()

        expect(streamSpy).toHaveBeenCalledTimes(1)
    })

    it('stops the underlying retry and clears the scheduled reconnect when aborted', () => {
        const streamSpy = jest.spyOn(api, 'stream').mockResolvedValue(undefined)
        const connection = createStreamConnection({
            url: new URL('https://example.com/events'),
            token: 'token',
            onMessage: jest.fn(),
        })
        const streamOptions = streamSpy.mock.calls[0][1]
        const error = new Error('connection lost')

        expect(() => streamOptions.onError(error)).toThrow(error)

        connection.abort()
        jest.advanceTimersByTime(1000)
        expect(streamSpy).toHaveBeenCalledTimes(1)
    })

    describe('stream response metadata', () => {
        it.each(['GET', 'POST'] as const)('forwards healthy %s responses, including reconnects', async (method) => {
            const responses = [
                new Response(null, { headers: { 'X-Request-ID': '11111111-1111-4111-8111-111111111111' } }),
                new Response(null, { headers: { 'X-Request-ID': '22222222-2222-4222-8222-222222222222' } }),
            ]
            const controller = new AbortController()
            const onOpen = jest.fn()
            const onError = jest.fn()
            const fetchEventSourceSpy = jest
                .spyOn(fetchEventSourceModule, 'fetchEventSource')
                .mockImplementationOnce(async (_url, options) => {
                    for (const response of responses) {
                        await options?.onopen?.(response)
                    }
                    controller.abort()
                    expect(options?.signal?.aborted).toBe(true)
                })

            try {
                await api.stream('/api/projects/2/dashboards/21/stream_query_results/', {
                    ...(method === 'POST' ? { method, data: {} } : { method }),
                    signal: controller.signal,
                    onMessage: jest.fn(),
                    onOpen,
                    onError,
                })
                expect(onOpen.mock.calls).toEqual(responses.map((response) => [response]))
                expect(onError).not.toHaveBeenCalled()
            } finally {
                fetchEventSourceSpy.mockRestore()
            }
        })

        it.each([403, 429])('does not open an unhealthy response with status %s', async (status) => {
            const onOpen = jest.fn()
            const onError = jest.fn()
            const fetchEventSourceSpy = jest
                .spyOn(fetchEventSourceModule, 'fetchEventSource')
                .mockImplementationOnce(async (_url, options) => {
                    await options?.onopen?.(
                        new Response('{}', {
                            status,
                            headers: { 'Content-Type': 'application/json', 'Retry-After': '1' },
                        })
                    )
                    expect(options?.signal?.aborted).toBe(true)
                })

            try {
                await api.stream('/api/projects/2/dashboards/21/stream_query_results/', {
                    onMessage: jest.fn(),
                    onOpen,
                    onError,
                })
                expect(onOpen).not.toHaveBeenCalled()
                expect(onError).toHaveBeenCalledTimes(1)
            } finally {
                fetchEventSourceSpy.mockRestore()
            }
        })
    })
})
