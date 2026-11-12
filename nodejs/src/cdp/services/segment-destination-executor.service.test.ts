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

type RecordedRequest = { url: string; method: string; headers: Record<string, string>; body: any }

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
                'Error executing function on event uuid: Request failed with status 403 ({"error":"Forbidden"})',
            ],
            [
                'hands the response back when the destination turns off throwHttpErrors',
                'segment-actions-gameball',
                gameballInputs,
                undefined,
            ],
        ])('does not retry a 403 and %s', async (_name, templateId, inputs, expectedError) => {
            const fn = createHogFunction({ name: 'Plugin test', template_id: templateId })
            const requests = fakeDestinationServer(403, { error: 'Forbidden' })

            const result = await service.execute(createExampleSegmentInvocation(fn, inputs))

            expect(requests).toHaveLength(1)
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

            const invocation = createExampleSegmentInvocation(fn, amplitudeInputs)
            const requests = fakeDestinationServer(429, { error: 'Too many requests' })

            let minBackoffMs = DateTime.utc().plus({ milliseconds: defaultConfig.CDP_FETCH_BACKOFF_BASE_MS }).toMillis()
            const result = await service.execute(invocation)

            expect(result.finished).toBe(false)
            expect(result.logs).toContainEqual(
                expect.objectContaining({
                    level: 'warn',
                    message: 'HTTP request failed with status 429 ({"error":"Too many requests"}). Scheduling retry...',
                })
            )

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

            let maxBackoffMs = DateTime.utc()
                .plus({ milliseconds: defaultConfig.CDP_FETCH_BACKOFF_BASE_MS * 2 })
                .toMillis()
            let scheduledAt = result.invocation.queueScheduledAt!.toMillis()
            expect(scheduledAt).toBeGreaterThanOrEqual(minBackoffMs)
            expect(scheduledAt).toBeLessThan(maxBackoffMs)

            // second fetch call

            minBackoffMs = DateTime.utc()
                .plus({ milliseconds: defaultConfig.CDP_FETCH_BACKOFF_BASE_MS * 2 })
                .toMillis()
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

            maxBackoffMs = DateTime.utc()
                .plus({ milliseconds: defaultConfig.CDP_FETCH_BACKOFF_BASE_MS * 3 })
                .toMillis()
            scheduledAt = invocationResults2.invocation.queueScheduledAt!.toMillis()
            expect(scheduledAt).toBeGreaterThanOrEqual(minBackoffMs)
            expect(scheduledAt).toBeLessThan(maxBackoffMs)

            // third fetch call

            const invocationResults3 = await service.execute(invocationResults2.invocation)

            expect(invocationResults3.finished).toBe(true)
            expect(invocationResults3.error?.message).toContain('Request failed with status 429')

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
