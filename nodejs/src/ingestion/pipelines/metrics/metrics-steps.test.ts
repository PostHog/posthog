import { Message } from 'node-rdkafka'

import { AppMetricsOutput } from '~/common/outputs'
import { isDevEnv } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'
import { PipelineResult, isDlqResult, isDropResult, isOkResult } from '~/ingestion/framework/results'
import { createTestMessage } from '~/tests/helpers/kafka-message'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'
import { createTestTeam } from '~/tests/helpers/team'

import { createDropQuotaLimitedStep } from './drop-quota-limited-step'
import { recordMetricsIngested } from './ingestion-otel-metrics'
import { metricMessageDlqCounter, metricMessageDroppedCounter } from './metrics'
import { MetricsUsageAccumulator } from './metrics-usage'
import { createEmitMetricsUsageStep } from './metrics-usage-steps'
import { DEFAULT_METRICS_RETENTION_DAYS, METRICS_OUTPUT, MetricsOutput } from './outputs/outputs'
import { createParseMetricsHeadersStep } from './parse-metrics-headers-step'
import { createProduceMetricsStep } from './produce-metrics-step'
import { createRateLimitMetricsStep } from './rate-limit-metrics-step'
import { createResolveMetricsTeamStep } from './resolve-metrics-team-step'

jest.mock('~/common/utils/logger', () => ({
    logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))
jest.mock('~/common/utils/env-utils', () => ({
    ...jest.requireActual('~/common/utils/env-utils'),
    isDevEnv: jest.fn().mockReturnValue(false),
}))
jest.mock('./ingestion-otel-metrics', () => ({ recordMetricsIngested: jest.fn() }))

function toHeaders(headers: Record<string, string>): Message['headers'] {
    return Object.entries(headers).map(([key, value]) => ({ [key]: Buffer.from(value) }))
}

async function counterValue(
    counter: typeof metricMessageDroppedCounter,
    labels: { reason: string; team_id: string }
): Promise<number> {
    const { values } = await counter.get()
    const match = values.find((v) => v.labels.reason === labels.reason && v.labels.team_id === labels.team_id)
    return match?.value ?? 0
}

function expectDrop(result: PipelineResult<unknown>, reason: string): void {
    expect(isDropResult(result)).toBe(true)
    if (isDropResult(result)) {
        expect(result.reason).toBe(reason)
    }
}

describe('metrics ingestion steps', () => {
    let usage: MetricsUsageAccumulator

    beforeEach(() => {
        jest.clearAllMocks()
        metricMessageDroppedCounter.reset()
        metricMessageDlqCounter.reset()
        usage = new MetricsUsageAccumulator()
    })

    describe('parseMetricsHeadersStep', () => {
        const step = createParseMetricsHeadersStep()

        it('reads token and size headers, defaulting missing sizes to 0', async () => {
            const message = createTestMessage({
                headers: toHeaders({ token: 'tok', bytes_uncompressed: '120', record_count: '3' }),
            })
            const result = await step({ message })
            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value).toMatchObject({
                    token: 'tok',
                    bytesUncompressed: 120,
                    bytesCompressed: 0,
                    recordCount: 3,
                })
            }
        })

        it.each([
            ['missing_token', toHeaders({ bytes_uncompressed: '10' })],
            ['parse_error', [{ token: null as unknown as Buffer }]],
        ])('drops with %s and counts it against team "unknown"', async (reason, headers) => {
            const result = await step({ message: createTestMessage({ headers }) })
            expectDrop(result, reason)
            expect(await counterValue(metricMessageDroppedCounter, { reason, team_id: 'unknown' })).toBe(1)
        })

        it.each([['abc'], ['12abc'], ['-5'], ['1.5'], ['']])(
            'sends a message with size header %p to the DLQ instead of poisoning the usage counters',
            async (value) => {
                const result = await step({
                    message: createTestMessage({ headers: toHeaders({ token: 'tok', record_count: value }) }),
                })
                expect(isDlqResult(result) && result.reason).toBe('invalid_size_header')
                expect(
                    await counterValue(metricMessageDlqCounter, { reason: 'invalid_size_header', team_id: 'unknown' })
                ).toBe(1)
            }
        )
    })

    describe('resolveMetricsTeamStep', () => {
        const teamManager = { getTeam: jest.fn(), getTeamByToken: jest.fn() }
        const step = createResolveMetricsTeamStep(teamManager)

        it('drops an unknown token', async () => {
            teamManager.getTeamByToken.mockResolvedValueOnce(null)
            const result = await step({ token: 'tok' })
            expectDrop(result, 'team_not_found')
            expect(
                await counterValue(metricMessageDroppedCounter, { reason: 'team_not_found', team_id: 'unknown' })
            ).toBe(1)
        })

        it('sends a failed lookup to the DLQ so the message stays replayable', async () => {
            teamManager.getTeamByToken.mockRejectedValueOnce(new Error('pg down'))
            const result = await step({ token: 'tok' })
            expect(isDlqResult(result) && result.reason).toBe('team_lookup_error')
            expect(
                await counterValue(metricMessageDlqCounter, { reason: 'team_lookup_error', team_id: 'unknown' })
            ).toBe(1)
        })

        it('maps phc_local to team 1 only in dev', async () => {
            jest.mocked(isDevEnv).mockReturnValueOnce(true)
            teamManager.getTeam.mockResolvedValueOnce(createTestTeam({ id: 1 }))
            const result = await step({ token: 'phc_local' })
            expect(isOkResult(result) && result.value.teamId).toBe(1)
            expect(teamManager.getTeam).toHaveBeenCalledWith(1)
            expect(teamManager.getTeamByToken).not.toHaveBeenCalled()
        })
    })

    describe('dropQuotaLimitedStep', () => {
        const quotaLimiting = { isTeamTokenQuotaLimited: jest.fn() }
        const step = createDropQuotaLimitedStep(quotaLimiting)
        const input = { token: 'tok', teamId: 7, bytesUncompressed: 500, recordCount: 4 }

        it('drops a quota-limited team and records the drop as usage', async () => {
            quotaLimiting.isTeamTokenQuotaLimited.mockResolvedValueOnce(true)
            const result = await step({ ...input, usage })
            expectDrop(result, 'quota_limited')
            expect(quotaLimiting.isTeamTokenQuotaLimited).toHaveBeenCalledWith('tok', 'metrics_mb_ingested')
            expect([...usage.entries()]).toEqual([
                [7, expect.objectContaining({ bytesDropped: 500, recordsDropped: 4 })],
            ])
            expect(await counterValue(metricMessageDroppedCounter, { reason: 'quota_limited', team_id: '7' })).toBe(1)
        })
    })

    describe('rateLimitMetricsStep', () => {
        const makeValue = (teamId: number, bytesUncompressed: number) => ({
            token: `tok-${teamId}`,
            teamId,
            message: createTestMessage(),
            bytesUncompressed,
            bytesCompressed: 0,
            recordCount: 1,
            usage,
        })

        it('returns one result per input in input order, dropping what the limiter dropped', async () => {
            const values = [makeValue(1, 100), makeValue(1, 200), makeValue(2, 300)]
            const rateLimiter = {
                filterMessages: jest.fn().mockResolvedValue({ allowed: [values[0], values[2]], dropped: [values[1]] }),
            }
            const results = await createRateLimitMetricsStep(rateLimiter)(values)

            expect(results).toHaveLength(3)
            expect(isOkResult(results[0]) && results[0].value).toBe(values[0])
            expectDrop(results[1], 'rate_limited')
            expect(isOkResult(results[2]) && results[2].value).toBe(values[2])
            expect(rateLimiter.filterMessages).toHaveBeenCalledTimes(1)
            expect(new Map(usage.entries())).toEqual(
                new Map([
                    [
                        1,
                        expect.objectContaining({
                            bytesAllowed: 100,
                            recordsAllowed: 1,
                            bytesDropped: 200,
                            recordsDropped: 1,
                        }),
                    ],
                    [2, expect.objectContaining({ bytesAllowed: 300, recordsAllowed: 1 })],
                ])
            )
            expect(await counterValue(metricMessageDroppedCounter, { reason: 'rate_limited', team_id: '1' })).toBe(1)
        })
    })

    describe('produceMetricsStep', () => {
        let outputs: jest.Mocked<ReturnType<typeof createMockIngestionOutputs<MetricsOutput>>>
        const value = Buffer.from('opaque avro packet')
        const input = {
            message: createTestMessage({
                value,
                headers: toHeaders({ token: 'tok', record_count: '3', 'retention-days': '7', batch_uuid: 'b1' }),
            }),
            token: 'tok',
            teamId: 7,
            bytesUncompressed: 300,
            recordCount: 3,
        }

        beforeEach(() => {
            outputs = createMockIngestionOutputs<MetricsOutput>()
        })

        it('produces the packet unchanged with the ClickHouse headers and credits it after the ack', async () => {
            const result = await createProduceMetricsStep(outputs)(input)

            expect(isOkResult(result)).toBe(true)
            expect(outputs.produce).toHaveBeenCalledWith(METRICS_OUTPUT, {
                value,
                key: null,
                headers: {
                    token: 'tok',
                    team_id: '7',
                    record_count: '3',
                    'retention-days': String(DEFAULT_METRICS_RETENTION_DAYS),
                    batch_uuid: 'b1',
                },
            })
            expect(recordMetricsIngested).toHaveBeenCalledWith(7, 300, 3)
        })

        it('sends the message to the DLQ and does not credit it when the produce fails', async () => {
            outputs.produce.mockRejectedValueOnce(new Error('broker down'))
            const result = await createProduceMetricsStep(outputs)(input)

            expect(isDlqResult(result) && result.reason).toBe('metrics_produce_failed')
            expect(recordMetricsIngested).not.toHaveBeenCalled()
            expect(await counterValue(metricMessageDlqCounter, { reason: 'Error', team_id: '7' })).toBe(1)
        })

        it('drops a message with no value', async () => {
            const result = await createProduceMetricsStep(outputs)({
                ...input,
                message: createTestMessage({ value: null }),
            })
            expectDrop(result, 'null_value')
            expect(outputs.produce).not.toHaveBeenCalled()
        })
    })

    describe('emitMetricsUsageStep', () => {
        let outputs: jest.Mocked<ReturnType<typeof createMockIngestionOutputs<AppMetricsOutput>>>

        beforeEach(() => {
            outputs = createMockIngestionOutputs<AppMetricsOutput>()
        })

        it('logs and resolves when the usage produce fails', async () => {
            usage.recordReceived(1, 100, 2)
            outputs.queueMessages.mockRejectedValueOnce(new Error('broker down'))

            const result = await createEmitMetricsUsageStep(outputs)({ batchContext: { usage } })
            await expect(Promise.all(result.sideEffects)).resolves.toBeDefined()
            expect(logger.error).toHaveBeenCalledWith(
                '🔴',
                'Failed to emit usage metrics - billing data may be lost',
                expect.anything()
            )
        })
    })
})
