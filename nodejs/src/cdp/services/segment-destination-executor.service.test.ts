import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime, Settings } from 'luxon'

import { defaultConfig } from '~/common/config/config'
import { parseJSON } from '~/common/utils/json-parse'

import { createHogFunction } from '../_tests/fixtures'
import {
    amplitudeInputs,
    createExampleSegmentInvocation,
    gameballInputs,
    pipedriveResponse,
} from '../_tests/fixtures-segment'
import { SEGMENT_DESTINATIONS_BY_ID } from '../segment/segment-templates'
import { SegmentDestinationExecutorService } from './segment-destination-executor.service'

type RecordedRequest = { url: string; method: string; headers: Record<string, string>; body: unknown }

const fakeDestinationServer = (status: number, responseBody: unknown): RecordedRequest[] => {
    const requests: RecordedRequest[] = []
    mockFetch.mockImplementation((url, options) => {
        requests.push({
            url,
            method: options.method,
            headers: options.headers,
            body: options.body === undefined ? undefined : parseJSON(options.body),
        })
        return Promise.resolve({
            status,
            json: () => Promise.resolve(responseBody),
            text: () => Promise.resolve(JSON.stringify(responseBody)),
            headers: {},
            dump: () => Promise.resolve(),
        } as any)
    })
    return requests
}

const AMPLITUDE_URL = 'https://api2.amplitude.com/2/httpapi'

describe('SegmentDestinationExecutorService', () => {
    let service: SegmentDestinationExecutorService

    const amplitudePlugin = SEGMENT_DESTINATIONS_BY_ID['segment-actions-amplitude']
    const amplitudeAction = amplitudePlugin.destination.actions['logEventV2']

    const pipedrivePlugin = SEGMENT_DESTINATIONS_BY_ID['segment-actions-pipedrive']
    const pipedriveActivitiesAction = pipedrivePlugin.destination.actions['createUpdateActivity']

    beforeEach(() => {
        mockFetch.mockReset()

        Settings.defaultZone = 'UTC'
        service = new SegmentDestinationExecutorService(defaultConfig)

        fakeDestinationServer(200, {})

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
        jest.spyOn(amplitudeAction as any, 'perform')
        jest.spyOn(pipedriveActivitiesAction as any, 'perform')
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('segment plugins', () => {
        it('sends the destination request built from the inputs', async () => {
            const fn = createHogFunction({
                name: 'Plugin test',
                template_id: 'segment-actions-amplitude',
                inputs_schema: amplitudePlugin.template.inputs_schema,
            })
            const requests = fakeDestinationServer(200, { code: 200, events_ingested: 1 })

            const result = await service.execute(createExampleSegmentInvocation(fn, amplitudeInputs))

            expect(requests).toEqual([
                {
                    url: AMPLITUDE_URL,
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: {
                        api_key: 'api-key',
                        events: [
                            expect.objectContaining({
                                user_id: 'user-id',
                                device_id: 'device-id',
                                platform: 'Desktop',
                                city: 'Sydney',
                                country: 'Australia',
                                user_properties: expect.objectContaining({ email: 'max@posthog.com' }),
                            }),
                        ],
                    },
                },
            ])
            expect(result.finished).toBe(true)
            expect(result.error).toBeUndefined()
            expect(result.logs.at(-1)).toMatchObject({
                level: 'info',
                message: expect.stringMatching(/^Function completed in/),
            })
            expect(JSON.stringify(result.logs)).not.toContain(amplitudeInputs.secretKey)
        })

        it('should redact a credential input that a stale stored schema leaves non-secret', async () => {
            const fn = createHogFunction({
                name: 'Plugin test',
                template_id: 'segment-actions-amplitude',
                inputs_schema: amplitudePlugin.template.inputs_schema.map((schema) => ({ ...schema, secret: false })),
            })

            const invocation = createExampleSegmentInvocation(fn, amplitudeInputs)

            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({}),
                text: () => Promise.resolve('{}'),
                headers: {},
                dump: () => Promise.resolve(),
            })

            const result = await service.execute(invocation)

            expect(result.finished).toBe(true)
            const logs = JSON.stringify(result.logs)
            expect(logs).toContain('fetchOptions')
            expect(logs).not.toContain(amplitudeInputs.apiKey)
            expect(logs).not.toContain(amplitudeInputs.secretKey)
        })

        it('should redact secrets in an error thrown by the destination', async () => {
            const fn = createHogFunction({
                name: 'Plugin test',
                template_id: 'segment-actions-amplitude',
                inputs_schema: amplitudePlugin.template.inputs_schema,
            })
            const invocation = createExampleSegmentInvocation(fn, amplitudeInputs)
            jest.mocked(amplitudeAction.perform!).mockRejectedValueOnce(
                new Error(`Destination rejected ${amplitudeInputs.secretKey}`)
            )

            const result = await service.execute(invocation)

            expect(String(result.error)).toBe('Error: Destination rejected ***REDACTED***')
            expect(JSON.stringify(result.logs)).not.toContain(amplitudeInputs.secretKey)
        })

        it.each([
            [
                'fails the invocation when the destination throws on HTTP errors',
                'segment-actions-amplitude',
                amplitudeInputs,
                { url: AMPLITUDE_URL, method: 'POST', headers: { 'Content-Type': 'application/json' } },
                'Error executing function on event uuid: Request failed with status 403 ({"error":"Forbidden"})',
            ],
            [
                'hands the response back when the destination turns off throwHttpErrors',
                'segment-actions-gameball',
                gameballInputs,
                {
                    url: 'https://api.gameball.co/api/v3.0/integrations/event',
                    method: 'POST',
                    headers: { APIKey: 'abc', 'Content-Type': 'application/json', 'x-gb-agent': 'GB/Segment' },
                    body: {
                        events: { $web_vitals: expect.objectContaining({ $geoip_city_name: 'Aylesbury' }) },
                        playerUniqueId: expect.any(String),
                    },
                },
                undefined,
            ],
        ])('does not retry a 403 and %s', async (_name, templateId, inputs, expectedRequest, expectedError) => {
            const fn = createHogFunction({ name: 'Plugin test', template_id: templateId })
            const requests = fakeDestinationServer(403, { error: 'Forbidden' })

            const result = await service.execute(createExampleSegmentInvocation(fn, inputs))

            expect(requests).toEqual([expect.objectContaining(expectedRequest)])
            expect(result.finished).toBe(true)
            expect(result.invocation.queueScheduledAt).toBeUndefined()
            expect(result.error?.message).toEqual(expectedError)
            expect(result.logs).toContainEqual(
                expect.objectContaining({
                    level: 'warn',
                    message: 'HTTP request failed with status 403 ({"error":"Forbidden"}). ',
                })
            )
            expect(result.logs.at(-1)).toMatchObject(
                expectedError
                    ? { level: 'error', message: `Function failed: ${expectedError}` }
                    : { level: 'info', message: expect.stringMatching(/^Function completed in/) }
            )
        })

        it('should retry retryable fetch errors', async () => {
            const fn = createHogFunction({
                name: 'Plugin test',
                template_id: 'segment-actions-amplitude',
            })
            const requests = fakeDestinationServer(429, { error: 'Too many requests' })
            const now = DateTime.utc().toMillis()
            const backoffBaseMs = defaultConfig.CDP_FETCH_BACKOFF_BASE_MS

            const result1 = await service.execute(createExampleSegmentInvocation(fn, amplitudeInputs))

            expect(result1.finished).toBe(false)
            expect(result1.logs).toContainEqual(
                expect.objectContaining({
                    level: 'warn',
                    message: 'HTTP request failed with status 429 ({"error":"Too many requests"}). Scheduling retry...',
                })
            )
            expect(result1.invocation).toMatchObject({ queue: 'hog', queueMetadata: { tries: 1 }, queuePriority: 1 })
            const firstDelayMs = result1.invocation.queueScheduledAt!.toMillis() - now
            expect(firstDelayMs).toBeGreaterThanOrEqual(backoffBaseMs)
            expect(firstDelayMs).toBeLessThan(backoffBaseMs * 2)

            const result2 = await service.execute(result1.invocation)

            expect(result2.finished).toBe(false)
            expect(result2.invocation).toMatchObject({ queue: 'hog', queueMetadata: { tries: 2 }, queuePriority: 2 })
            const secondDelayMs = result2.invocation.queueScheduledAt!.toMillis() - now
            expect(secondDelayMs).toBeGreaterThanOrEqual(backoffBaseMs * 2)
            expect(secondDelayMs).toBeLessThan(backoffBaseMs * 3)

            const result3 = await service.execute(result2.invocation)

            expect(result3.finished).toBe(true)
            expect(result3.error?.message).toContain('Request failed with status 429')
            expect(result3.invocation).toMatchObject({ queueMetadata: { tries: 3 }, queuePriority: 0 })
            expect(result3.invocation.queueScheduledAt).toBeUndefined()
            expect(requests.map((request) => request.url)).toEqual([AMPLITUDE_URL, AMPLITUDE_URL, AMPLITUDE_URL])
        })

        it('sends each request of a multi-request destination in order', async () => {
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
            const requests = fakeDestinationServer(200, pipedriveResponse)

            const result = await service.execute(createExampleSegmentInvocation(fn, pipedriveInputs))

            expect(requests).toEqual([
                {
                    url: 'https://posthog-sandbox.pipedrive.com/api/v1/itemSearch/field?term=max%40posthog.com&field_key=email&exact_match=true&field_type=personField&return_item_ids=true&api_token=api-key',
                    method: 'GET',
                    headers: {},
                    body: undefined,
                },
                {
                    url: 'https://posthog-sandbox.pipedrive.com/api/v1/persons?api_token=api-key',
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: { name: 'Max', email: 'max@posthog.com', phone: null },
                },
            ])
            expect(result.finished).toBe(true)
            expect(result.logs.filter((log) => log.message.startsWith('endpoint, ')).map((log) => log.message)).toEqual(
                [
                    'endpoint, https://posthog-sandbox.pipedrive.com/api/v1/itemSearch/field',
                    'endpoint, https://posthog-sandbox.pipedrive.com/api/v1/persons',
                ]
            )
        })

        it('handles activity_id field correctly for pipedrive activities action', async () => {
            jest.spyOn(pipedriveActivitiesAction as any, 'perform')

            const testCases = [
                { activity_id: null, shouldHaveId: false },
                { activity_id: '', shouldHaveId: false },
                { activity_id: '15', shouldHaveId: true },
            ]

            for (const testCase of testCases) {
                mockFetch.mockReset()

                const pipedriveInputs = {
                    domain: 'posthog-sandbox',
                    apiToken: 'api-key',
                    person_match_value: 'e252ca85-9ea2-4d17-9d99-5fda5535995d',
                    activity_id: testCase.activity_id,
                    personField: 'id',
                    organization_match_value: '',
                    organizationField: 'id',
                    deal_match_value: null,
                    dealField: 'id',
                    subject: null,
                    type: null,
                    description: null,
                    note: null,
                    due_date: null,
                    due_time: null,
                    duration: null,
                    done: null,
                    internal_partner_action: 'createUpdateActivity',
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
                    dump: () => Promise.resolve(),
                })

                await service.execute(invocation)

                expect(mockFetch).toHaveBeenCalledTimes(2)

                const requestBody = parseJSON(mockFetch.mock.calls[1][1].body)
                const endpoint = mockFetch.mock.calls[1][0]

                if (testCase.shouldHaveId) {
                    expect(endpoint).toBe(
                        `https://posthog-sandbox.pipedrive.com/api/v1/activities/${testCase.activity_id}?api_token=api-key`
                    )
                } else {
                    expect(requestBody).not.toHaveProperty('id')
                    expect(endpoint).toBe('https://posthog-sandbox.pipedrive.com/api/v1/activities?api_token=api-key')
                }
            }
        })

        it.each([
            ['omits them when enabled', true, false],
            ['keeps them when disabled', false, true],
        ])('internal_omit_empty_values %s', async (_name, omitEmptyValues, expectEmptyValues) => {
            const fn = createHogFunction({
                name: 'Plugin test',
                template_id: 'segment-actions-iterable',
            })

            const invocation = createExampleSegmentInvocation(fn, {
                apiKey: 'api-key',
                dataCenterLocation: 'united_states',
                email: 'max@posthog.com',
                userId: 'user-id',
                phoneNumber: null,
                dataFields: {
                    plan: 'enterprise',
                    // The customer-facing case: a property that is only set on some events
                    last_seen_at: null,
                    company: '',
                },
                mergeNestedObjects: true,
                internal_partner_action: 'updateUser',
                internal_omit_empty_values: omitEmptyValues,
            })

            await service.execute(invocation)

            expect(mockFetch).toHaveBeenCalledTimes(1)
            const requestBody = parseJSON(mockFetch.mock.calls[0][1].body)

            expect(requestBody.email).toBe('max@posthog.com')
            expect(requestBody.dataFields.plan).toBe('enterprise')

            expect('last_seen_at' in requestBody.dataFields).toBe(expectEmptyValues)
            expect('company' in requestBody.dataFields).toBe(expectEmptyValues)
            expect('phoneNumber' in requestBody.dataFields).toBe(expectEmptyValues)
        })
    })
})
