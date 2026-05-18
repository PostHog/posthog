import { Clickhouse } from '~/../tests/helpers/clickhouse'
import { waitForExpect } from '~/../tests/helpers/expectations'
import {
    EventBuilder,
    createKafkaMessages,
    createTestWithTeamIngester,
    fetchEvents,
    waitForClickHouseKafkaConsumer,
    waitForKafkaMessages,
} from '~/../tests/helpers/ingestion-e2e'
import { createTestIngestionOutputs, createTestMonitoringOutputs } from '~/../tests/helpers/ingestion-outputs'
import { resetKafka } from '~/../tests/helpers/kafka'
import { resetTestDatabase } from '~/../tests/helpers/sql'

import { createHogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { UUIDT } from '../../utils/utils'
import { ClickhouseGroupRepository } from '../../worker/ingestion/groups/repositories/clickhouse-group-repository'
import { assembleAiConsumer } from './consumer'

jest.mock('~/utils/token-bucket', () => {
    const mockConsume = jest.fn().mockReturnValue(true)
    return {
        IngestionWarningLimiter: {
            consume: mockConsume,
        },
    }
})

jest.mock('../../utils/logger')

describe.each([{ PERSONS_PREFETCH_ENABLED: false }, { PERSONS_PREFETCH_ENABLED: true }])(
    'AI Consumer E2E (prefetch=$PERSONS_PREFETCH_ENABLED)',
    (prefetchConfig) => {
        const testWithTeamIngester = createTestWithTeamIngester(prefetchConfig, (hub, kafkaProducer) => {
            const outputs = createTestIngestionOutputs(kafkaProducer)
            return assembleAiConsumer(hub, {
                ...hub,
                hogTransformer: createHogTransformerService(hub, {
                    ...hub,
                    monitoringOutputs: createTestMonitoringOutputs(kafkaProducer),
                }),
                outputs,
                clickhouseGroupRepository: new ClickhouseGroupRepository(outputs),
            })
        })
        let clickhouse: Clickhouse

        beforeAll(async () => {
            clickhouse = Clickhouse.create()
            await resetKafka()
            await resetTestDatabase()
            await clickhouse.resetTestDatabase()
            await waitForClickHouseKafkaConsumer(clickhouse)
            process.env.SITE_URL = 'https://example.com'
        })

        afterAll(async () => {
            await resetTestDatabase()
            await clickhouse.resetTestDatabase()
            clickhouse.close()
        })

        testWithTeamIngester(
            'should route $ai_generation events through AI subpipeline with full enrichment',
            {},
            async ({ hub, team, kafkaProducer, ingester, token }) => {
                const distinctId = new UUIDT().toString()
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$ai_generation')
                                .withProperties({
                                    $ai_model: 'gpt-4',
                                    $ai_provider: 'openai',
                                    $ai_input_tokens: 100,
                                    $ai_output_tokens: 50,
                                    $ai_trace_id: 12345,
                                    $ai_parent_id: 67890,
                                    $ai_model_parameters: {
                                        temperature: 0.7,
                                        stream: true,
                                        max_tokens: 1024,
                                    },
                                    $ai_output_choices: JSON.stringify([
                                        {
                                            role: 'assistant',
                                            message: {
                                                tool_calls: [
                                                    { function: { name: 'get_weather' } },
                                                    { function: { name: 'search_docs' } },
                                                ],
                                            },
                                        },
                                    ]),
                                })
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)
                await waitForExpect(async () => {
                    const events = await fetchEvents(clickhouse, team.id)
                    expect(events.length).toBe(1)
                    const props = events[0].properties

                    // Cost calculation: input/output/total costs from token counts + model pricing
                    expect(props.$ai_input_cost_usd).toBeGreaterThan(0)
                    expect(props.$ai_output_cost_usd).toBeGreaterThan(0)
                    expect(props.$ai_total_cost_usd).toBeGreaterThan(0)
                    expect(props.$ai_total_cost_usd).toBe(props.$ai_input_cost_usd + props.$ai_output_cost_usd)

                    // Cost model metadata
                    expect(props.$ai_model_cost_used).toBeDefined()
                    expect(props.$ai_cost_model_provider).toBeDefined()

                    // Trace property normalization: numeric IDs converted to strings
                    expect(props.$ai_trace_id).toBe('12345')
                    expect(props.$ai_parent_id).toBe('67890')

                    // Model parameter extraction: promoted to top-level properties
                    expect(props.$ai_temperature).toBe(0.7)
                    expect(props.$ai_stream).toBe(true)
                    expect(props.$ai_max_tokens).toBe(1024)

                    // Tool call extraction: parsed from $ai_output_choices
                    expect(props.$ai_tools_called).toBe('get_weather,search_docs')
                    expect(props.$ai_tool_call_count).toBe(2)
                })

                expect(hub).toBeDefined() // satisfy lint: hub is destructured for parity with other tests
            }
        )

        testWithTeamIngester(
            'should split AI events with large properties when splitting is enabled',
            {
                pluginServerConfig: {
                    INGESTION_AI_EVENT_SPLITTING_ENABLED: true,
                    INGESTION_AI_EVENT_SPLITTING_TEAMS: '*',
                    INGESTION_AI_EVENT_SPLITTING_STRIP_HEAVY_TEAMS: '*',
                },
            },
            async ({ hub, team, kafkaProducer, ingester, token }) => {
                const distinctId = new UUIDT().toString()
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$ai_generation')
                                .withProperties({
                                    $ai_model: 'gpt-4',
                                    $ai_provider: 'openai',
                                    $ai_input_tokens: 100,
                                    $ai_output_tokens: 50,
                                    $ai_input: 'What is the meaning of life?',
                                    $ai_output: 'The meaning of life is 42.',
                                })
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)
                await waitForExpect(async () => {
                    const events = await fetchEvents(clickhouse, team.id)
                    // Main events topic: stripped of large AI input/output text
                    const mainEvent = events.find((e) => e.event === '$ai_generation')
                    expect(mainEvent).toBeDefined()
                    expect(mainEvent!.properties.$ai_model).toBe('gpt-4')
                    expect(mainEvent!.properties.$ai_input).toBeUndefined()
                    expect(mainEvent!.properties.$ai_output).toBeUndefined()
                })

                expect(hub).toBeDefined()
            }
        )

        testWithTeamIngester(
            'should route $ai_trace events through AI subpipeline with trace normalization',
            {},
            async ({ hub, team, kafkaProducer, ingester, token }) => {
                const distinctId = new UUIDT().toString()
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$ai_trace')
                                .withProperties({
                                    $ai_trace_id: 'trace-abc',
                                    $ai_span_id: 99999,
                                    $ai_session_id: true,
                                })
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)
                await waitForExpect(async () => {
                    const events = await fetchEvents(clickhouse, team.id)
                    expect(events.length).toBe(1)
                    const props = events[0].properties

                    // Trace normalization applied to all AI events
                    expect(props.$ai_trace_id).toBe('trace-abc')
                    expect(props.$ai_span_id).toBe('99999')
                    expect(props.$ai_session_id).toBe('true')

                    // No cost enrichment for $ai_trace events
                    expect(props.$ai_input_cost_usd).toBeUndefined()
                    expect(props.$ai_output_cost_usd).toBeUndefined()
                    expect(props.$ai_total_cost_usd).toBeUndefined()
                })

                expect(hub).toBeDefined()
            }
        )
    }
)
