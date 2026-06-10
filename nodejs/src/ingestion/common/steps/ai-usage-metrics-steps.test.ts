import { createTestEventHeaders } from '../../../../tests/helpers/event-headers'
import { createTestTeam } from '../../../../tests/helpers/team'
import { parseJSON } from '../../../utils/json-parse'
import { IngestionOutputs } from '../../outputs/ingestion-outputs'
import { isOkResult, ok } from '../../pipelines/results'
import { AiUsageBatchAppMetrics } from '../ai-usage/batch-app-metrics'
import { AppMetricsOutput } from '../outputs'
import {
    AI_USAGE_BYTES_RECEIVED,
    AI_USAGE_BYTES_RECEIVED_COMPRESSED,
    createAiUsageBatchAppMetricsBeforeBatchStep,
    createFlushAiUsageBatchAppMetricsStep,
    createTrackAiUsageMetricsStep,
} from './ai-usage-metrics-steps'

describe('ai-usage-metrics-steps', () => {
    const mockOutputs = {
        queueMessages: jest.fn().mockResolvedValue(undefined),
    } as unknown as jest.Mocked<Pick<IngestionOutputs<AppMetricsOutput>, 'queueMessages'>> &
        IngestionOutputs<AppMetricsOutput>

    const team = createTestTeam({ id: 42 })

    function makePipelineContext(extra: Record<string, unknown> = {}) {
        return { sideEffects: [], warnings: [], ...extra }
    }

    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('createAiUsageBatchAppMetricsBeforeBatchStep', () => {
        it('merges an aggregator into the batch context and each element, preserving prior context', async () => {
            const step = createAiUsageBatchAppMetricsBeforeBatchStep<{ existing: number }, unknown, { prior: string }>(
                mockOutputs
            )
            const result = await step({
                elements: [{ result: ok({ existing: 1, prior: 'x' }), context: makePipelineContext() }],
                batchContext: { prior: 'x' },
                batchId: 0,
            })

            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }
            const aggregator = result.value.batchContext.aiUsageBatchAppMetrics
            expect(aggregator).toBeInstanceOf(AiUsageBatchAppMetrics)
            expect(result.value.batchContext.prior).toBe('x')
            expect(result.value.elements[0].result.value.aiUsageBatchAppMetrics).toBe(aggregator)
            expect(result.value.elements[0].result.value.existing).toBe(1)
        })
    })

    describe('createTrackAiUsageMetricsStep', () => {
        it('records uncompressed and compressed bytes for an AI event with size headers', async () => {
            const aiUsageBatchAppMetrics = new AiUsageBatchAppMetrics(mockOutputs)
            const step = createTrackAiUsageMetricsStep(true)
            const input = {
                team,
                headers: createTestEventHeaders({
                    event: '$ai_generation',
                    ai_bytes_uncompressed: 2048,
                    ai_bytes_compressed: 512,
                }),
                aiUsageBatchAppMetrics,
            }

            const result = await step(input)
            expect(isOkResult(result)).toBe(true)

            await aiUsageBatchAppMetrics.flush()
            expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)
            const [, messages] = mockOutputs.queueMessages.mock.calls[0]
            const rows = messages.map((m: { value: Buffer }) => parseJSON(m.value.toString()))
            const byName = Object.fromEntries(rows.map((r: any) => [r.metric_name, r]))

            expect(byName[AI_USAGE_BYTES_RECEIVED]).toMatchObject({
                team_id: 42,
                app_source: 'llm_analytics',
                metric_kind: 'usage',
                count: 2048,
            })
            expect(byName[AI_USAGE_BYTES_RECEIVED_COMPRESSED]).toMatchObject({ count: 512 })
        })

        it('is a no-op when disabled', async () => {
            const aiUsageBatchAppMetrics = new AiUsageBatchAppMetrics(mockOutputs)
            const step = createTrackAiUsageMetricsStep(false)
            await step({
                team,
                headers: createTestEventHeaders({
                    event: '$ai_generation',
                    ai_bytes_uncompressed: 2048,
                    ai_bytes_compressed: 512,
                }),
                aiUsageBatchAppMetrics,
            })

            await aiUsageBatchAppMetrics.flush()
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
        })

        it('is a no-op when no size headers are present', async () => {
            const aiUsageBatchAppMetrics = new AiUsageBatchAppMetrics(mockOutputs)
            const step = createTrackAiUsageMetricsStep(true)
            await step({
                team,
                headers: createTestEventHeaders({ event: '$ai_generation' }),
                aiUsageBatchAppMetrics,
            })

            await aiUsageBatchAppMetrics.flush()
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
        })

        it('ignores size headers stamped on a non-AI event', async () => {
            const aiUsageBatchAppMetrics = new AiUsageBatchAppMetrics(mockOutputs)
            const step = createTrackAiUsageMetricsStep(true)
            await step({
                team,
                headers: createTestEventHeaders({
                    event: '$pageview',
                    ai_bytes_uncompressed: 999,
                    ai_bytes_compressed: 100,
                }),
                aiUsageBatchAppMetrics,
            })

            await aiUsageBatchAppMetrics.flush()
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
        })

        it('sums bytes across events from the same team into one row per metric', async () => {
            const aiUsageBatchAppMetrics = new AiUsageBatchAppMetrics(mockOutputs)
            const step = createTrackAiUsageMetricsStep(true)
            for (const bytes of [100, 250]) {
                await step({
                    team,
                    headers: createTestEventHeaders({
                        event: '$ai_span',
                        ai_bytes_uncompressed: bytes,
                        ai_bytes_compressed: bytes,
                    }),
                    aiUsageBatchAppMetrics,
                })
            }

            await aiUsageBatchAppMetrics.flush()
            const [, messages] = mockOutputs.queueMessages.mock.calls[0]
            const rows = messages.map((m: { value: Buffer }) => parseJSON(m.value.toString()))
            expect(rows).toHaveLength(2)
            const uncompressed = rows.find((r: any) => r.metric_name === AI_USAGE_BYTES_RECEIVED)
            expect(uncompressed.count).toBe(350)
        })
    })

    describe('createFlushAiUsageBatchAppMetricsStep', () => {
        it('flushes the aggregator from the batch context as a side effect', async () => {
            const aiUsageBatchAppMetrics = new AiUsageBatchAppMetrics(mockOutputs)
            aiUsageBatchAppMetrics.increment(team.id, AI_USAGE_BYTES_RECEIVED, 4096)

            const step = createFlushAiUsageBatchAppMetricsStep()
            const result = await step({ batchContext: { aiUsageBatchAppMetrics } })

            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }
            expect(result.sideEffects).toHaveLength(1)
            await Promise.all(result.sideEffects ?? [])
            expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)
        })
    })
})
