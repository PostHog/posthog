import { DateTime, Settings } from 'luxon'

import { defaultConfig } from '~/config/config'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { fetch, FetchResponse } from '~/utils/request'

import { createHogFunction } from '../_tests/fixtures'
import { createExampleNativeInvocation } from '../_tests/fixtures-segment'
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
    let mockFetch: jest.Mock<Promise<FetchResponse>, Parameters<typeof fetch>>

    beforeEach(() => {
        Settings.defaultZone = 'UTC'
        service = new NativeDestinationExecutorService(defaultConfig)

        service.fetch = mockFetch = jest.fn((_url, _options) =>
            Promise.resolve({
                status: 200,
                json: () => Promise.resolve({}),
                text: () => Promise.resolve(JSON.stringify({})),
                headers: {},
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
                queue: 'native',
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
                queue: 'native',
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
                queue: 'native',
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
                queue: 'native',
                queueMetadata: { tries: 3 },
                queueParameters: undefined,
                queuePriority: 0,
                queueScheduledAt: undefined,
                queueSource: undefined,
                state: expect.any(Object),
                teamId: 1,
            })
        })

        it('should handle throwHttpErrors flag', async () => {
            // This destination is setting the throwHttpErrors flag to false, so we should return the error to the function instead.
            // https://github.com/segmentio/action-destinations/blob/main/packages/destination-actions/src/destinations/gameball/util.ts#L68
            jest.spyOn(gameballAction as any, 'perform')

            const fn = createHogFunction({
                name: 'Plugin test',
                template_id: 'segment-actions-gameball',
            })

            const invocation = createExampleSegmentInvocation(fn, gameballInputs)

            mockFetch.mockResolvedValue({
                status: 403,
                json: () => Promise.resolve({ error: 'Forbidden' }),
                text: () => Promise.resolve(JSON.stringify({ error: 'Forbidden' })),
                headers: { 'retry-after': '60' },
            })

            const result = await service.execute(invocation)

            expect(result.finished).toBe(true)

            result.logs.forEach((x) => {
                if (typeof x.message === 'string' && x.message.includes('Function completed in')) {
                    x.message = 'Function completed in [REPLACED]'
                }
            })

            expect(result.logs).toMatchSnapshot()

            expect(gameballAction.perform).toHaveBeenCalledTimes(1)
            expect(forSnapshot(jest.mocked(gameballAction.perform!).mock.calls[0][1])).toMatchSnapshot()

            expect(mockFetch).toHaveBeenCalledTimes(1)
            expect(forSnapshot(mockFetch.mock.calls[0])).toMatchInlineSnapshot(`
                [
                  "https://api.gameball.co/api/v3.0/integrations/event",
                  {
                    "body": "{"events":{"$web_vitals":{"$geoip_city_name":"Aylesbury","$geoip_country_name":"United Kingdom","$geoip_country_code":"GB","$geoip_continent_name":"Europe","$geoip_continent_code":"EU","$geoip_postal_code":"HP21","$geoip_latitude":51.8053,"$geoip_longitude":-0.8086,"$geoip_accuracy_radius":500,"$geoip_time_zone":"Europe/London","$geoip_subdivision_1_code":"ENG","$geoip_subdivision_1_name":"England","$geoip_subdivision_2_code":"BKM","$geoip_subdivision_2_name":"Buckinghamshire"}},"playerUniqueId":"<REPLACED-UUID-0>"}",
                    "headers": {
                      "APIKey": "abc",
                      "Content-Type": "application/json",
                      "x-gb-agent": "GB/Segment",
                    },
                    "method": "POST",
                  },
                ]
            `)

            expect(result.invocation).toEqual({
                hogFunction: expect.any(Object),
                functionId: expect.any(String),
                id: expect.any(String),
                queue: 'native',
                queueMetadata: { tries: 1 },
                queueParameters: undefined,
                queuePriority: 0,
                queueScheduledAt: undefined,
                queueSource: undefined,
                state: expect.any(Object),
                teamId: 1,
            })
        })

        it('works with multiple fetches', async () => {
            jest.spyOn(pipedriveAction as any, 'perform')

            const pipedriveInputs = {
                domain: 'posthog-sandbox',
                match_field: 'email',
                apiToken: 'api-key',
                match_value: 'max@posthog.com',
                personField: 'id',
                name: 'Max',
                organizationField: 'id',
                email: 'max@posthog.com',
                dealField: 'id',
                phone: null,
                custom_fields: {},
                internal_partner_action: 'createUpdatePerson',
                debug_mode: true,
            }

            const fn = createHogFunction({
                name: 'Plugin test',
                template_id: 'segment-actions-pipedrive',
            })

            const invocation = createExampleSegmentInvocation(fn, pipedriveInputs)

            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({ total_count: 1 }),
                text: () => Promise.resolve(JSON.stringify(pipedriveResponse)),
                headers: {},
            })

            const result = await service.execute(invocation)

            expect(result.finished).toBe(true)

            result.logs.forEach((x) => {
                if (typeof x.message === 'string' && x.message.includes('Function completed in')) {
                    x.message = 'Function completed in [REPLACED]'
                }
            })

            expect(result.logs).toMatchSnapshot()

            expect(pipedriveAction.perform).toHaveBeenCalledTimes(1)
            expect(forSnapshot(jest.mocked(pipedriveAction.perform!).mock.calls[0][1])).toMatchSnapshot()

            expect(mockFetch).toHaveBeenCalledTimes(2)
            expect(forSnapshot(mockFetch.mock.calls[0])).toMatchInlineSnapshot(`
                [
                  "https://posthog-sandbox.pipedrive.com/api/v1/itemSearch/field?term=max%40posthog.com&field_key=email&exact_match=true&field_type=personField&return_item_ids=true&api_token=api-key",
                  {
                    "body": undefined,
                    "headers": {},
                    "method": "GET",
                  },
                ]
            `)
            expect(forSnapshot(mockFetch.mock.calls[1])).toMatchInlineSnapshot(`
                [
                  "https://posthog-sandbox.pipedrive.com/api/v1/persons?api_token=api-key",
                  {
                    "body": "{"name":"Max","email":"max@posthog.com","phone":null}",
                    "headers": {
                      "Content-Type": "application/json",
                    },
                    "method": "POST",
                  },
                ]
            `)

            expect(result.finished).toBe(true)
        })
    })
})
