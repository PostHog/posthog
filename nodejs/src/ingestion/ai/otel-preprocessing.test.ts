import { Message } from 'node-rdkafka'

import { KAFKA_EVENTS_PLUGIN_INGESTION } from '../../config/kafka-topics'
import { KafkaProducerWrapper, MessageKey } from '../../kafka/producer'
import { EventHeaders, IncomingEventWithTeam, PipelineEvent, ProjectId, Team } from '../../types'
import { PostTeamPreprocessingSubpipelineInput } from '../analytics/post-team-preprocessing-subpipeline'
import { PipelineResultType } from '../pipelines/results'
import { createExpandOtelRawDataStep } from './otel-preprocessing'

const createMockKafkaProducer = () => {
    return {
        produce: jest.fn().mockResolvedValue(undefined),
    } as unknown as KafkaProducerWrapper
}

const createMockTeam = (): Team => ({
    id: 1,
    uuid: 'test-team-uuid',
    project_id: 1 as ProjectId,
    organization_id: 'test-org-id',
    name: 'Test Team',
    anonymize_ips: false,
    api_token: 'test-token',
    slack_incoming_webhook: null,
    session_recording_opt_in: true,
    person_processing_opt_out: false,
    heatmaps_opt_in: null,
    ingested_event: true,
    person_display_name_properties: null,
    test_account_filters: null,
    cookieless_server_hash_mode: null,
    timezone: 'UTC',
    available_features: [],
    drop_events_older_than_seconds: null,
})

const createMockHeaders = (): EventHeaders => ({
    token: 'test-token',
    distinct_id: 'user-123',
    force_disable_person_processing: false,
    historical_migration: false,
})

const createMockEvent = (event: string, properties: Record<string, unknown> = {}): PipelineEvent => ({
    event,
    distinct_id: 'user-123',
    properties,
    uuid: 'test-uuid',
    timestamp: new Date().toISOString(),
    ip: '127.0.0.1',
    site_url: 'https://app.posthog.com',
    now: new Date().toISOString(),
})

const createMockInput = (event: PipelineEvent, token?: string): PostTeamPreprocessingSubpipelineInput => {
    const team = createMockTeam()
    const headers = createMockHeaders()
    if (token) {
        headers.token = token
    }
    const eventWithTeam: IncomingEventWithTeam = {
        message: {} as Message,
        event: { ...event, token: token ?? headers.token },
        team,
        headers,
    }
    return {
        headers,
        eventWithTeam,
        team,
    }
}

describe('createExpandOtelRawDataStep', () => {
    describe('when event is not $ai_raw_data', () => {
        it('passes through non-AI events unchanged', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(createMockEvent('$pageview'))

            const result = await step(input)

            expect(result.type).toBe(PipelineResultType.OK)
            expect(kafkaProducer.produce).not.toHaveBeenCalled()
        })

        it('passes through AI events unchanged', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(createMockEvent('$ai_generation'))

            const result = await step(input)

            expect(result.type).toBe(PipelineResultType.OK)
            expect(kafkaProducer.produce).not.toHaveBeenCalled()
        })
    })

    describe('when event is $ai_raw_data but not otel_trace format', () => {
        it('passes through with different format', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(createMockEvent('$ai_raw_data', { format: 'other_format' }))

            const result = await step(input)

            expect(result.type).toBe(PipelineResultType.OK)
            expect(kafkaProducer.produce).not.toHaveBeenCalled()
        })

        it('passes through with no format', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(createMockEvent('$ai_raw_data'))

            const result = await step(input)

            expect(result.type).toBe(PipelineResultType.OK)
            expect(kafkaProducer.produce).not.toHaveBeenCalled()
        })
    })

    describe('when event is $ai_raw_data with otel_trace format', () => {
        it('drops event with invalid otel data (missing resourceSpans)', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(
                createMockEvent('$ai_raw_data', {
                    format: 'otel_trace',
                    data: {},
                })
            )

            const result = await step(input)

            expect(result.type).toBe(PipelineResultType.DROP)
            if (result.type === PipelineResultType.DROP) {
                expect(result.reason).toBe('invalid_otel_data')
            }
            expect(kafkaProducer.produce).not.toHaveBeenCalled()
        })

        it('expands single span to single AI event', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(
                createMockEvent('$ai_raw_data', {
                    format: 'otel_trace',
                    data: {
                        resourceSpans: [
                            {
                                resource: { attributes: { 'service.name': 'my-service' } },
                                scopeSpans: [
                                    {
                                        spans: [
                                            {
                                                traceId: 'trace-123',
                                                spanId: 'span-456',
                                                parentSpanId: 'parent-789',
                                                startTimeUnixNano: '1704067200000000000',
                                                attributes: {
                                                    'gen_ai.operation.name': 'chat',
                                                    'gen_ai.request.model': 'gpt-4',
                                                    'gen_ai.usage.input_tokens': 100,
                                                    'gen_ai.usage.output_tokens': 50,
                                                },
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                })
            )

            const result = await step(input)

            expect(result.type).toBe(PipelineResultType.DROP)
            if (result.type === PipelineResultType.DROP) {
                expect(result.reason).toBe('otel_expanded')
                expect(result.sideEffects).toHaveLength(1)
            }

            expect(kafkaProducer.produce).toHaveBeenCalledTimes(1)
            const call = (kafkaProducer.produce as jest.Mock).mock.calls[0][0]
            expect(call.topic).toBe(KAFKA_EVENTS_PLUGIN_INGESTION)
            expect(call.key).toBe('test-token:user-123')

            const produced = JSON.parse(call.value.toString())
            expect(produced.token).toBe('test-token')
            expect(produced.distinct_id).toBe('user-123')
            expect(produced.uuid).toBeDefined()

            const eventData = JSON.parse(produced.data)
            expect(eventData.event).toBe('$ai_generation')
            expect(eventData.distinct_id).toBe('user-123')
            expect(eventData.properties.$ai_trace_id).toBe('trace-123')
            expect(eventData.properties.$ai_span_id).toBe('span-456')
            expect(eventData.properties.$ai_parent_id).toBe('parent-789')
            expect(eventData.properties.$ai_model).toBe('gpt-4')
            expect(eventData.properties.$ai_input_tokens).toBe(100)
            expect(eventData.properties.$ai_output_tokens).toBe(50)
            expect(eventData.properties.$ai_ingestion_source).toBe('otel')
            expect(eventData.properties['service.name']).toBe('my-service')
            expect(eventData.timestamp).toBe('2024-01-01T00:00:00.000Z')
        })

        it('expands multiple spans to multiple AI events', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(
                createMockEvent('$ai_raw_data', {
                    format: 'otel_trace',
                    data: {
                        resourceSpans: [
                            {
                                resource: { attributes: {} },
                                scopeSpans: [
                                    {
                                        spans: [
                                            {
                                                traceId: 'trace-1',
                                                spanId: 'span-1',
                                                attributes: { 'gen_ai.operation.name': 'chat' },
                                            },
                                            {
                                                traceId: 'trace-1',
                                                spanId: 'span-2',
                                                attributes: { 'gen_ai.operation.name': 'embeddings' },
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                })
            )

            const result = await step(input)

            expect(result.type).toBe(PipelineResultType.DROP)
            if (result.type === PipelineResultType.DROP) {
                expect(result.sideEffects).toHaveLength(2)
            }

            expect(kafkaProducer.produce).toHaveBeenCalledTimes(2)

            const firstCall = JSON.parse((kafkaProducer.produce as jest.Mock).mock.calls[0][0].value.toString())
            const secondCall = JSON.parse((kafkaProducer.produce as jest.Mock).mock.calls[1][0].value.toString())

            expect(JSON.parse(firstCall.data).event).toBe('$ai_generation')
            expect(JSON.parse(secondCall.data).event).toBe('$ai_embedding')
        })

        it('maps gen_ai.operation.name to correct event types', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const testCases = [
                { operationName: 'chat', expectedEvent: '$ai_generation' },
                { operationName: 'embeddings', expectedEvent: '$ai_embedding' },
                { operationName: 'unknown', expectedEvent: '$ai_span' },
                { operationName: undefined, expectedEvent: '$ai_span' },
            ]

            for (const { operationName, expectedEvent } of testCases) {
                ;(kafkaProducer.produce as jest.Mock).mockClear()

                const attributes: Record<string, unknown> = {}
                if (operationName !== undefined) {
                    attributes['gen_ai.operation.name'] = operationName
                }

                const input = createMockInput(
                    createMockEvent('$ai_raw_data', {
                        format: 'otel_trace',
                        data: {
                            resourceSpans: [
                                {
                                    scopeSpans: [
                                        {
                                            spans: [{ traceId: 'trace-1', spanId: 'span-1', attributes }],
                                        },
                                    ],
                                },
                            ],
                        },
                    })
                )

                await step(input)

                const produced = JSON.parse((kafkaProducer.produce as jest.Mock).mock.calls[0][0].value.toString())
                expect(JSON.parse(produced.data).event).toBe(expectedEvent)
            }
        })

        it('maps OTel attributes to PostHog properties', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(
                createMockEvent('$ai_raw_data', {
                    format: 'otel_trace',
                    data: {
                        resourceSpans: [
                            {
                                scopeSpans: [
                                    {
                                        spans: [
                                            {
                                                traceId: 'trace-id',
                                                spanId: 'span-id',
                                                attributes: {
                                                    'gen_ai.input.messages': [{ role: 'user', content: 'Hello' }],
                                                    'gen_ai.output.messages': [
                                                        { role: 'assistant', content: 'Hi there!' },
                                                    ],
                                                    'gen_ai.usage.input_tokens': 10,
                                                    'gen_ai.usage.output_tokens': 5,
                                                    'gen_ai.request.model': 'gpt-4',
                                                    'gen_ai.provider.name': 'openai',
                                                    'custom.attribute': 'custom-value',
                                                },
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                })
            )

            await step(input)

            const produced = JSON.parse((kafkaProducer.produce as jest.Mock).mock.calls[0][0].value.toString())
            const properties = JSON.parse(produced.data).properties

            expect(properties.$ai_trace_id).toBe('trace-id')
            expect(properties.$ai_span_id).toBe('span-id')
            expect(properties.$ai_input).toEqual([{ role: 'user', content: 'Hello' }])
            expect(properties.$ai_output_choices).toEqual([{ role: 'assistant', content: 'Hi there!' }])
            expect(properties.$ai_input_tokens).toBe(10)
            expect(properties.$ai_output_tokens).toBe(5)
            expect(properties.$ai_model).toBe('gpt-4')
            expect(properties.$ai_provider).toBe('openai')
            expect(properties['custom.attribute']).toBe('custom-value')
        })

        it('JSON parses string values for input and output', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(
                createMockEvent('$ai_raw_data', {
                    format: 'otel_trace',
                    data: {
                        resourceSpans: [
                            {
                                scopeSpans: [
                                    {
                                        spans: [
                                            {
                                                traceId: 'trace-id',
                                                spanId: 'span-id',
                                                attributes: {
                                                    'gen_ai.input.messages':
                                                        '[{"role": "user", "content": "Hello"}]',
                                                    'gen_ai.output.messages':
                                                        '[{"role": "assistant", "content": "Hi there!"}]',
                                                },
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                })
            )

            await step(input)

            const produced = JSON.parse((kafkaProducer.produce as jest.Mock).mock.calls[0][0].value.toString())
            const properties = JSON.parse(produced.data).properties

            expect(properties.$ai_input).toEqual([{ role: 'user', content: 'Hello' }])
            expect(properties.$ai_output_choices).toEqual([{ role: 'assistant', content: 'Hi there!' }])
        })

        it('keeps original string if JSON parsing fails', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(
                createMockEvent('$ai_raw_data', {
                    format: 'otel_trace',
                    data: {
                        resourceSpans: [
                            {
                                scopeSpans: [
                                    {
                                        spans: [
                                            {
                                                traceId: 'trace-id',
                                                spanId: 'span-id',
                                                attributes: {
                                                    'gen_ai.input.messages': 'not valid json',
                                                    'gen_ai.output.messages': '{broken',
                                                },
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                })
            )

            await step(input)

            const produced = JSON.parse((kafkaProducer.produce as jest.Mock).mock.calls[0][0].value.toString())
            const properties = JSON.parse(produced.data).properties

            expect(properties.$ai_input).toBe('not valid json')
            expect(properties.$ai_output_choices).toBe('{broken')
        })

        it('includes resource attributes in event properties', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(
                createMockEvent('$ai_raw_data', {
                    format: 'otel_trace',
                    data: {
                        resourceSpans: [
                            {
                                resource: {
                                    attributes: {
                                        'service.name': 'my-llm-service',
                                        'deployment.environment': 'production',
                                    },
                                },
                                scopeSpans: [
                                    {
                                        spans: [{ traceId: 'trace-1', spanId: 'span-1', attributes: {} }],
                                    },
                                ],
                            },
                        ],
                    },
                })
            )

            await step(input)

            const produced = JSON.parse((kafkaProducer.produce as jest.Mock).mock.calls[0][0].value.toString())
            const properties = JSON.parse(produced.data).properties

            expect(properties['service.name']).toBe('my-llm-service')
            expect(properties['deployment.environment']).toBe('production')
        })

        it('handles spans without parentSpanId', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(
                createMockEvent('$ai_raw_data', {
                    format: 'otel_trace',
                    data: {
                        resourceSpans: [
                            {
                                scopeSpans: [
                                    {
                                        spans: [
                                            {
                                                traceId: 'trace-1',
                                                spanId: 'span-1',
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                })
            )

            await step(input)

            const produced = JSON.parse((kafkaProducer.produce as jest.Mock).mock.calls[0][0].value.toString())
            const properties = JSON.parse(produced.data).properties

            expect(properties.$ai_parent_id).toBeUndefined()
        })

        it('handles multiple resourceSpans and scopeSpans', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(
                createMockEvent('$ai_raw_data', {
                    format: 'otel_trace',
                    data: {
                        resourceSpans: [
                            {
                                resource: { attributes: { 'service.name': 'service-1' } },
                                scopeSpans: [
                                    { spans: [{ traceId: 'trace-1', spanId: 'span-1' }] },
                                    { spans: [{ traceId: 'trace-1', spanId: 'span-2' }] },
                                ],
                            },
                            {
                                resource: { attributes: { 'service.name': 'service-2' } },
                                scopeSpans: [{ spans: [{ traceId: 'trace-2', spanId: 'span-3' }] }],
                            },
                        ],
                    },
                })
            )

            await step(input)

            expect(kafkaProducer.produce).toHaveBeenCalledTimes(3)

            const calls = (kafkaProducer.produce as jest.Mock).mock.calls
            const properties1 = JSON.parse(JSON.parse(calls[0][0].value.toString()).data).properties
            const properties2 = JSON.parse(JSON.parse(calls[1][0].value.toString()).data).properties
            const properties3 = JSON.parse(JSON.parse(calls[2][0].value.toString()).data).properties

            expect(properties1['service.name']).toBe('service-1')
            expect(properties2['service.name']).toBe('service-1')
            expect(properties3['service.name']).toBe('service-2')
        })

        it('uses event token over header token', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(
                createMockEvent('$ai_raw_data', {
                    format: 'otel_trace',
                    data: {
                        resourceSpans: [
                            { scopeSpans: [{ spans: [{ traceId: 'trace-1', spanId: 'span-1' }] }] },
                        ],
                    },
                }),
                'event-token'
            )
            input.headers.token = 'header-token'

            await step(input)

            const call = (kafkaProducer.produce as jest.Mock).mock.calls[0][0]
            expect(call.key).toBe('event-token:user-123')
            expect(JSON.parse(call.value.toString()).token).toBe('event-token')
        })

        it('drops event if no token available', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(
                createMockEvent('$ai_raw_data', {
                    format: 'otel_trace',
                    data: {
                        resourceSpans: [
                            { scopeSpans: [{ spans: [{ traceId: 'trace-1', spanId: 'span-1' }] }] },
                        ],
                    },
                })
            )
            input.eventWithTeam.event.token = undefined
            input.headers.token = undefined

            const result = await step(input)

            expect(result.type).toBe(PipelineResultType.DROP)
            if (result.type === PipelineResultType.DROP) {
                expect(result.reason).toBe('missing_token')
            }
            expect(kafkaProducer.produce).not.toHaveBeenCalled()
        })

        it('handles BigInt startTimeUnixNano', async () => {
            const kafkaProducer = createMockKafkaProducer()
            const step = createExpandOtelRawDataStep(kafkaProducer)

            const input = createMockInput(
                createMockEvent('$ai_raw_data', {
                    format: 'otel_trace',
                    data: {
                        resourceSpans: [
                            {
                                scopeSpans: [
                                    {
                                        spans: [
                                            {
                                                traceId: 'trace-1',
                                                spanId: 'span-1',
                                                startTimeUnixNano: 1704067200000000000,
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                })
            )

            await step(input)

            const produced = JSON.parse((kafkaProducer.produce as jest.Mock).mock.calls[0][0].value.toString())
            expect(JSON.parse(produced.data).timestamp).toBe('2024-01-01T00:00:00.000Z')
        })
    })
})
