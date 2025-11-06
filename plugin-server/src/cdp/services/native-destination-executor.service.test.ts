import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime, Settings } from 'luxon'

import { defaultConfig } from '~/config/config'
import { forSnapshot } from '~/tests/helpers/snapshots'

import { createHogFunction } from '../_tests/fixtures'
import { createExampleNativeInvocation } from '../_tests/fixtures-native'
import { NativeDestinationExecutorService } from './native-destination-executor.service'

const inputs = {
    url: 'https://posthog.com/webhook',
    method: 'POST',
    body: {
        event_name: '$pageview',
    },
    headers: {
        Authorization: 'Bearer abc',
    },
    debug_mode: true,
}

describe('NativeDestinationExecutorService', () => {
    let service: NativeDestinationExecutorService

    beforeEach(() => {
        Settings.defaultZone = 'UTC'
        service = new NativeDestinationExecutorService(defaultConfig)

        mockFetch.mockImplementation((_url, _options) =>
            Promise.resolve({
                status: 200,
                json: () => Promise.resolve({}),
                text: () => Promise.resolve(JSON.stringify({})),
                headers: {},
                dump: () => Promise.resolve(),
            } as any)
        )

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('native plugins', () => {
        it('should call the plugin perform method', async () => {
            const fn = createHogFunction({
                name: 'Plugin test',
                template_id: 'native-webhook',
            })

            const invocation = createExampleNativeInvocation(fn, inputs)

            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({ total_count: 1 }),
                text: () =>
                    Promise.resolve(
                        JSON.stringify({
                            code: 200,
                            server_upload_time: 1747910402315,
                            payload_size_bytes: 22207,
                            events_ingested: 1,
                        })
                    ),
                headers: {},
                dump: () => Promise.resolve(),
            })

            const result = await service.execute(invocation)

            expect(result.finished).toBe(true)

            result.logs.forEach((x) => {
                if (typeof x.message === 'string' && x.message.includes('Function completed in')) {
                    x.message = 'Function completed in [REPLACED]'
                }
            })

            expect(result.logs).toMatchSnapshot()

            expect(mockFetch).toHaveBeenCalledTimes(1)
            expect(forSnapshot(mockFetch.mock.calls[0])).toMatchInlineSnapshot(`
                [
                  "https://posthog.com/webhook",
                  {
                    "body": "{"event_name":"$pageview"}",
                    "headers": {
                      "Authorization": "Bearer abc",
                      "Content-Type": "application/json",
                      "User-Agent": "PostHog.com/1.0",
                    },
                    "method": "POST",
                  },
                ]
            `)
        })

        it('should handle non retryable fetch errors', async () => {
            const fn = createHogFunction({
                name: 'Plugin test',
                template_id: 'native-webhook',
            })

            const invocation = createExampleNativeInvocation(fn, inputs)

            mockFetch.mockResolvedValue({
                status: 403,
                json: () => Promise.resolve({ error: 'Forbidden' }),
                text: () => Promise.resolve(JSON.stringify({ error: 'Forbidden' })),
                headers: { 'retry-after': '60' },
                dump: () => Promise.resolve(),
            })

            const result = await service.execute(invocation)

            expect(result.finished).toBe(true)

            result.logs.forEach((x) => {
                if (typeof x.message === 'string' && x.message.includes('Function completed in')) {
                    x.message = 'Function completed in [REPLACED]'
                }
            })

            expect(result.logs).toMatchSnapshot()

            expect(mockFetch).toHaveBeenCalledTimes(1)
            expect(forSnapshot(mockFetch.mock.calls[0])).toMatchInlineSnapshot(`
                [
                  "https://posthog.com/webhook",
                  {
                    "body": "{"event_name":"$pageview"}",
                    "headers": {
                      "Authorization": "Bearer abc",
                      "Content-Type": "application/json",
                      "User-Agent": "PostHog.com/1.0",
                    },
                    "method": "POST",
                  },
                ]
            `)

            expect(result.invocation).toEqual({
                functionId: expect.any(String),
                hogFunction: expect.any(Object),
                id: expect.any(String),
                queue: 'hog',
                queueMetadata: {
                    tries: 1,
                },
                queuePriority: 0,
                queueParameters: undefined,
                queueScheduledAt: undefined,
                queueSource: undefined,
                state: expect.any(Object),
                teamId: 1,
            })
        })

        it('should retry retryable fetch errors', async () => {
            const fn = createHogFunction({
                name: 'Plugin test',
                template_id: 'native-webhook',
            })

            const invocation = createExampleNativeInvocation(fn, inputs)

            mockFetch.mockResolvedValue({
                status: 429,
                json: () => Promise.resolve({ error: 'Too many requests' }),
                text: () => Promise.resolve(JSON.stringify({ error: 'Too many requests' })),
                headers: { 'retry-after': '60' },
                dump: () => Promise.resolve(),
            })

            const result = await service.execute(invocation)

            expect(result.finished).toBe(false)

            result.logs.forEach((x) => {
                if (typeof x.message === 'string' && x.message.includes('Function completed in')) {
                    x.message = 'Function completed in [REPLACED]'
                }
            })

            expect(result.logs).toMatchSnapshot()

            expect(mockFetch).toHaveBeenCalledTimes(1)
            expect(forSnapshot(mockFetch.mock.calls[0])).toMatchInlineSnapshot(`
                [
                  "https://posthog.com/webhook",
                  {
                    "body": "{"event_name":"$pageview"}",
                    "headers": {
                      "Authorization": "Bearer abc",
                      "Content-Type": "application/json",
                      "User-Agent": "PostHog.com/1.0",
                    },
                    "method": "POST",
                  },
                ]
            `)

            expect(result.invocation).toEqual({
                hogFunction: expect.any(Object),
                functionId: expect.any(String),
                id: expect.any(String),
                queue: 'hog',
                queueMetadata: { tries: 1 },
                queueParameters: undefined,
                queuePriority: 1,
                queueScheduledAt: expect.any(Object),
                queueSource: undefined,
                state: expect.any(Object),
                teamId: 1,
            })

            let minBackoffMs = DateTime.utc().plus({ milliseconds: defaultConfig.CDP_FETCH_BACKOFF_BASE_MS }).toMillis()
            let maxBackoffMs = DateTime.utc()
                .plus({ milliseconds: defaultConfig.CDP_FETCH_BACKOFF_BASE_MS * 2 })
                .toMillis()
            let scheduledAt = result.invocation.queueScheduledAt!.toMillis()
            expect(scheduledAt > minBackoffMs && scheduledAt < maxBackoffMs).toBe(true)

            // second fetch call

            const invocationResults2 = await service.execute(result.invocation)

            expect(invocationResults2.finished).toBe(false)

            expect(invocationResults2.invocation).toEqual({
                hogFunction: expect.any(Object),
                functionId: expect.any(String),
                id: expect.any(String),
                queue: 'hog',
                queueMetadata: {
                    tries: 2,
                },
                queueParameters: undefined,
                queuePriority: 2,
                queueScheduledAt: expect.any(Object),
                queueSource: undefined,
                state: expect.any(Object),
                teamId: 1,
            })

            minBackoffMs = DateTime.utc()
                .plus({ milliseconds: defaultConfig.CDP_FETCH_BACKOFF_BASE_MS * 2 })
                .toMillis()
            maxBackoffMs = DateTime.utc()
                .plus({ milliseconds: defaultConfig.CDP_FETCH_BACKOFF_BASE_MS * 3 })
                .toMillis()
            scheduledAt = invocationResults2.invocation.queueScheduledAt!.toMillis()
            expect(scheduledAt > minBackoffMs && scheduledAt < maxBackoffMs).toBe(true)

            // third fetch call

            const invocationResults3 = await service.execute(invocationResults2.invocation)

            expect(invocationResults3.finished).toBe(true)

            expect(invocationResults3.invocation).toEqual({
                hogFunction: expect.any(Object),
                functionId: expect.any(String),
                id: expect.any(String),
                queue: 'hog',
                queueMetadata: { tries: 3 },
                queueParameters: undefined,
                queuePriority: 0,
                queueScheduledAt: undefined,
                queueSource: undefined,
                state: expect.any(Object),
                teamId: 1,
            })
        })

        // TODO: write tests for multiple fetches and the throwHttpErrors flag
    })
})
