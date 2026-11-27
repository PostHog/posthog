import { PipelineResultType, isDropResult, isOkResult } from '~/ingestion/framework/results'
import { createTestPluginEvent } from '~/tests/helpers/plugin-event'
import { createTestTeam } from '~/tests/helpers/team'

import { createCymbalProcessingStep } from './cymbal-processing-step'
import { CymbalClient } from './cymbal/client'
import { CymbalResult } from './cymbal/client'
import { CymbalResponse } from './cymbal/types'

describe('createCymbalProcessingStep', () => {
    let mockCymbalClient: jest.Mocked<CymbalClient>
    let step: ReturnType<typeof createCymbalProcessingStep>

    const team = createTestTeam({ id: 123 })

    const toOutcomes = (responses: (CymbalResponse | null)[]): CymbalResult[] =>
        responses.map((response) =>
            response ? { result: 'ok', value: response } : { result: 'drop', reason: 'suppressed' }
        )

    const createInput = (overrides: Partial<ReturnType<typeof createTestPluginEvent>> = {}) => ({
        event: createTestPluginEvent({
            event: '$exception',
            uuid: 'event-uuid-1',
            distinct_id: 'user-123',
            properties: {
                $exception_list: [{ type: 'Error', value: 'Test error' }],
            },
            ...overrides,
        }),
        team,
    })

    const createResponse = (overrides: Partial<CymbalResponse> = {}): CymbalResponse => ({
        uuid: 'event-uuid-1',
        event: '$exception',
        team_id: 123,
        timestamp: '2024-01-01T00:00:00Z',
        properties: {
            $exception_list: [{ type: 'Error', value: 'Test error' }],
            $exception_fingerprint: 'test-fingerprint',
            $exception_issue_id: 'test-issue-id',
        },
        ...overrides,
    })

    beforeEach(() => {
        mockCymbalClient = {
            processExceptions: jest.fn(),
            healthCheck: jest.fn(),
        } as unknown as jest.Mocked<CymbalClient>
        step = createCymbalProcessingStep(mockCymbalClient)
    })

    it('processes a batch of events through Cymbal', async () => {
        const inputs = [createInput({ uuid: 'uuid-1' }), createInput({ uuid: 'uuid-2' })]

        const responses = [
            createResponse({ uuid: 'uuid-1', properties: { $exception_fingerprint: 'fp-1' } }),
            createResponse({ uuid: 'uuid-2', properties: { $exception_fingerprint: 'fp-2' } }),
        ]

        mockCymbalClient.processExceptions.mockResolvedValueOnce(toOutcomes(responses))

        const results = await step(inputs)

        expect(results).toHaveLength(2)
        expect(results[0].type).toBe(PipelineResultType.OK)
        expect(results[1].type).toBe(PipelineResultType.OK)

        // Verify Cymbal request format
        expect(mockCymbalClient.processExceptions).toHaveBeenCalledWith([
            expect.objectContaining({
                estimatedSize: expect.any(Number),
                request: expect.objectContaining({
                    uuid: 'uuid-1',
                    event: '$exception',
                    team_id: 123,
                }),
            }),
            expect.objectContaining({
                estimatedSize: expect.any(Number),
                request: expect.objectContaining({
                    uuid: 'uuid-2',
                    event: '$exception',
                    team_id: 123,
                }),
            }),
        ])
    })

    it('enriches events with Cymbal response data', async () => {
        const input = createInput({
            properties: {
                $exception_list: [{ type: 'Error', value: 'Test error' }],
                existing: 'property',
            },
        })

        const response = createResponse({
            properties: {
                $exception_list: [{ type: 'Error', value: 'Test error', resolved: true } as any],
                $exception_fingerprint: 'computed-fingerprint',
                $exception_issue_id: 'issue-123',
                $exception_resolved: true,
            },
        })

        mockCymbalClient.processExceptions.mockResolvedValueOnce(toOutcomes([response]))

        const results = await step([input])

        expect(results[0].type).toBe(PipelineResultType.OK)
        if (isOkResult(results[0])) {
            // Cymbal replaces properties entirely
            expect(results[0].value.event.properties).toEqual(response.properties)
        }
    })

    it('drops suppressed events', async () => {
        const inputs = [createInput({ uuid: 'uuid-1' }), createInput({ uuid: 'uuid-2' })]

        mockCymbalClient.processExceptions.mockResolvedValueOnce(
            toOutcomes([
                null, // Suppressed
                createResponse({ uuid: 'uuid-2', properties: { $exception_fingerprint: 'fp-2' } }),
            ])
        )

        const results = await step(inputs)

        expect(results).toHaveLength(2)
        expect(results[0].type).toBe(PipelineResultType.DROP)
        expect(isDropResult(results[0])).toBe(true)
        expect(results[1].type).toBe(PipelineResultType.OK)
    })

    it('drops an event with the reason Cymbal gives', async () => {
        mockCymbalClient.processExceptions.mockResolvedValueOnce([{ result: 'drop', reason: 'rate_limited_per_issue' }])

        const results = await step([createInput()])

        expect(results[0]).toMatchObject({ type: PipelineResultType.DROP, reason: 'rate_limited_per_issue' })
    })

    it('sends an event Cymbal fails to the DLQ and keeps its neighbour', async () => {
        mockCymbalClient.processExceptions.mockResolvedValueOnce([
            { result: 'fail', error: { code: 'invalid_input', message: 'cannot process uuid-1' } },
            ...toOutcomes([createResponse({ uuid: 'uuid-2', properties: { $exception_fingerprint: 'fp-2' } })]),
        ])

        const results = await step([createInput({ uuid: 'uuid-1' }), createInput({ uuid: 'uuid-2' })])

        expect(results[0]).toMatchObject({
            type: PipelineResultType.DLQ,
            reason: 'cymbal_item_fail',
            error: expect.objectContaining({ message: 'invalid_input: cannot process uuid-1' }),
        })
        expect(results[1]).toMatchObject({
            type: PipelineResultType.OK,
            value: { event: { uuid: 'uuid-2', properties: { $exception_fingerprint: 'fp-2' } } },
        })
    })

    describe('an event Cymbal asks to retry', () => {
        const retry: CymbalResult = { result: 'retry', error: { code: 'deadline_exceeded', message: 'slow' } }
        const withAttempts = (attempts?: string) => ({
            ...createInput(),
            message: { headers: attempts === undefined ? [] : [{ 'cymbal-retry-attempts': Buffer.from(attempts) }] },
        })

        it('goes to the overflow lane from the main lane, also when the whole batch asks', async () => {
            step = createCymbalProcessingStep(mockCymbalClient, {
                overflowMode: 'redirect',
                preservePartitionLocality: false,
            })
            mockCymbalClient.processExceptions.mockResolvedValueOnce([retry, retry])

            const results = await step([createInput({ uuid: 'uuid-1' }), createInput({ uuid: 'uuid-2' })])

            for (const result of results) {
                expect(result).toMatchObject({
                    type: PipelineResultType.REDIRECT,
                    reason: 'cymbal_item_retry',
                    output: 'overflow',
                    preserveKey: false,
                })
            }
        })

        it.each([
            [undefined, '1'],
            ['1', '2'],
        ])('goes back on the overflow topic after %s earlier attempts there', async (attempts, next) => {
            step = createCymbalProcessingStep(mockCymbalClient, {
                overflowMode: 'consume',
                preservePartitionLocality: true,
            })
            mockCymbalClient.processExceptions.mockResolvedValueOnce([retry])

            const results = await step([withAttempts(attempts)])

            expect(results[0]).toMatchObject({
                type: PipelineResultType.REDIRECT,
                output: 'overflow',
                headers: { 'cymbal-retry-attempts': next },
            })
        })

        it.each([
            ['after its third attempt on the overflow lane', 'consume' as const, '2'],
            ['when the consumer has no overflow lane', 'disabled' as const, undefined],
        ])('goes to the DLQ %s', async (_name, overflowMode, attempts) => {
            step = createCymbalProcessingStep(mockCymbalClient, { overflowMode, preservePartitionLocality: true })
            mockCymbalClient.processExceptions.mockResolvedValueOnce([retry])

            const results = await step([withAttempts(attempts)])

            expect(results[0]).toMatchObject({ type: PipelineResultType.DLQ, reason: 'cymbal_item_retry' })
        })
    })

    it('passes all properties to Cymbal including GeoIP', async () => {
        const input = createInput({
            properties: {
                $exception_list: [{ type: 'Error', value: 'Test' }],
                $geoip_country_code: 'US',
                $geoip_city_name: 'San Francisco',
                $geoip_subdivision_1_code: 'CA',
                $geoip_subdivision_1_name: 'California',
            },
        })

        mockCymbalClient.processExceptions.mockResolvedValueOnce(toOutcomes([createResponse()]))

        await step([input])

        expect(mockCymbalClient.processExceptions).toHaveBeenCalledWith([
            expect.objectContaining({
                estimatedSize: expect.any(Number),
                request: expect.objectContaining({
                    properties: expect.objectContaining({
                        $geoip_country_code: 'US',
                        $geoip_city_name: 'San Francisco',
                        $geoip_subdivision_1_code: 'CA',
                        $geoip_subdivision_1_name: 'California',
                    }),
                }),
            }),
        ])
    })

    it('includes group properties in request properties', async () => {
        const input = createInput({
            properties: {
                $exception_list: [{ type: 'Error', value: 'Test' }],
                $group_0: 'company-1',
                $group_1: 'project-1',
            },
        })

        mockCymbalClient.processExceptions.mockResolvedValueOnce(toOutcomes([createResponse()]))

        await step([input])

        // Group properties are passed through in the properties object
        expect(mockCymbalClient.processExceptions).toHaveBeenCalledWith([
            expect.objectContaining({
                estimatedSize: expect.any(Number),
                request: expect.objectContaining({
                    properties: expect.objectContaining({
                        $group_0: 'company-1',
                        $group_1: 'project-1',
                    }),
                }),
            }),
        ])
    })

    it('handles empty batch', async () => {
        const results = await step([])

        expect(results).toEqual([])
        expect(mockCymbalClient.processExceptions).not.toHaveBeenCalled()
    })

    it('preserves team in output', async () => {
        const input = createInput()

        mockCymbalClient.processExceptions.mockResolvedValueOnce(toOutcomes([createResponse()]))

        const results = await step([input])

        expect(results[0].type).toBe(PipelineResultType.OK)
        if (isOkResult(results[0])) {
            expect(results[0].value.team).toBe(team)
        }
    })

    it('passes properties even when $exception_list is missing', async () => {
        const input = createInput({
            properties: { some_prop: 'value' }, // No $exception_list
        })

        mockCymbalClient.processExceptions.mockResolvedValueOnce(toOutcomes([createResponse()]))

        await step([input])

        expect(mockCymbalClient.processExceptions).toHaveBeenCalledWith([
            expect.objectContaining({
                estimatedSize: expect.any(Number),
                request: expect.objectContaining({
                    properties: { some_prop: 'value' },
                }),
            }),
        ])
    })

    describe('timestamp validation', () => {
        it('uses timestamp from event when valid', async () => {
            const input = createInput()
            input.event.timestamp = '2024-01-15T10:30:00.000Z'

            mockCymbalClient.processExceptions.mockResolvedValueOnce(toOutcomes([createResponse()]))

            await step([input])

            expect(mockCymbalClient.processExceptions).toHaveBeenCalledWith([
                expect.objectContaining({
                    estimatedSize: expect.any(Number),
                    request: expect.objectContaining({
                        timestamp: '2024-01-15T10:30:00.000Z',
                    }),
                }),
            ])
        })

        it('falls back to current time when timestamp is missing', async () => {
            jest.useFakeTimers()
            jest.setSystemTime(new Date('2024-01-20T12:00:00.000Z'))

            try {
                const input = createInput()
                input.event.timestamp = undefined as any

                mockCymbalClient.processExceptions.mockResolvedValueOnce(toOutcomes([createResponse()]))

                await step([input])

                expect(mockCymbalClient.processExceptions).toHaveBeenCalledWith([
                    expect.objectContaining({
                        estimatedSize: expect.any(Number),
                        request: expect.objectContaining({
                            timestamp: '2024-01-20T12:00:00.000Z',
                        }),
                    }),
                ])
            } finally {
                jest.useRealTimers()
            }
        })

        it('stores validated timestamp back on event for downstream steps', async () => {
            const input = createInput()
            input.event.timestamp = '2024-01-15T10:30:00.000Z'

            mockCymbalClient.processExceptions.mockResolvedValueOnce(toOutcomes([createResponse()]))

            const results = await step([input])

            expect(results[0].type).toBe(PipelineResultType.OK)
            if (isOkResult(results[0])) {
                // The validated timestamp should be stored on event.timestamp
                expect(results[0].value.event.timestamp).toBe('2024-01-15T10:30:00.000Z')
            }
        })

        it('emits warning for invalid timestamp and falls back to current time', async () => {
            const input = createInput()
            input.event.timestamp = 'not-a-valid-timestamp' as any

            mockCymbalClient.processExceptions.mockResolvedValueOnce(toOutcomes([createResponse()]))

            const results = await step([input])

            expect(results[0].type).toBe(PipelineResultType.OK)
            if (isOkResult(results[0])) {
                // Should have a timestamp warning
                expect(results[0].warnings.length).toBeGreaterThanOrEqual(1)
                expect(results[0].warnings.some((w) => w.type.includes('timestamp'))).toBe(true)
            }
        })
    })

    it('throws on Cymbal client error so Kafka retries the batch', async () => {
        const inputs = [createInput({ uuid: 'uuid-1' }), createInput({ uuid: 'uuid-2' })]

        mockCymbalClient.processExceptions.mockRejectedValueOnce(new Error('Cymbal unavailable'))

        // Error should propagate up so Kafka doesn't commit the offset and retries the batch
        await expect(step(inputs)).rejects.toThrow('Cymbal unavailable')
    })

    describe('ingestion warnings', () => {
        it('emits the warnings Cymbal reports for an event', async () => {
            const input = createInput({ uuid: 'event-with-errors' })
            const warning = {
                type: 'error_tracking_exception_processing_errors',
                details: {
                    eventUuid: 'event-with-errors',
                    errors: ['No sourcemap found for source url: https://example.com/app.js'],
                },
                key: 'event-with-errors',
            }

            mockCymbalClient.processExceptions.mockResolvedValueOnce([
                { result: 'ok', value: createResponse({ uuid: 'event-with-errors' }), warnings: [warning] },
            ])

            const results = await step([input])

            expect(results[0].type).toBe(PipelineResultType.OK)
            expect(results[0].warnings).toEqual([warning])
        })

        it('does not emit warning for suppressed events', async () => {
            const input = createInput({ uuid: 'suppressed-event' })

            mockCymbalClient.processExceptions.mockResolvedValueOnce(toOutcomes([null]))

            const results = await step([input])

            expect(results[0].type).toBe(PipelineResultType.DROP)
            // Drop results also have warnings array but it should be empty
            expect(results[0].warnings).toHaveLength(0)
        })
    })
})
