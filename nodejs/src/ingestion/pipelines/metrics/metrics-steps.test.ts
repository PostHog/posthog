import avro from 'avsc'
import { Message } from 'node-rdkafka'

import { AppMetricsOutput } from '~/common/outputs'
import { isDevEnv } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'
import { PipelineResult, isDlqResult, isDropResult, isOkResult } from '~/ingestion/framework/results'
import { createTestMessage } from '~/tests/helpers/kafka-message'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'
import { createTestTeam } from '~/tests/helpers/team'

import { createDecodeMetricsPacketStep } from './decode-metrics-packet-step'
import { createDropQuotaLimitedStep } from './drop-quota-limited-step'
import { recordMetricsIngested } from './ingestion-otel-metrics'
import { metricMessageDlqCounter, metricMessageDroppedCounter } from './metrics'
import { decodeMetricsPacket, encodeMetricsPacket } from './metrics-avro'
import { MetricsUsageAccumulator } from './metrics-usage'
import { createEmitMetricsUsageStep } from './metrics-usage-steps'
import { METRICS_OUTPUT, MetricsOutput } from './outputs/outputs'
import { createParseMetricsHeadersStep } from './parse-metrics-headers-step'
import { createRateLimitMetricsStep } from './rate-limit-metrics-step'
import { createRepackAndProduceMetricsStep, metricsRepackGroupKey } from './repack-metrics-step'
import { createResolveMetricsTeamStep } from './resolve-metrics-team-step'
import { MetricRecord } from './types'

jest.mock('~/common/utils/logger', () => ({
    logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))
jest.mock('~/common/utils/env-utils', () => ({
    ...jest.requireActual('~/common/utils/env-utils'),
    isDevEnv: jest.fn().mockReturnValue(false),
}))
jest.mock('./ingestion-otel-metrics', () => ({ recordMetricsIngested: jest.fn() }))

const TEST_RECORD_TYPE = avro.Type.forSchema({
    type: 'record',
    name: 'MetricRecord',
    fields: [
        { name: 'metric_name', type: 'string' },
        { name: 'value', type: 'double' },
    ],
})

function toHeaders(headers: Record<string, string>): Message['headers'] {
    return Object.entries(headers).map(([key, value]) => ({ [key]: Buffer.from(value) }))
}

function metricRecords(prefix: string, count: number): MetricRecord[] {
    return Array.from({ length: count }, (_, i) => ({ metric_name: `${prefix}_${i}`, value: i }))
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

    describe('decodeMetricsPacketStep', () => {
        const step = createDecodeMetricsPacketStep()

        it('decodes the Avro container into rows with a schema fingerprint', async () => {
            const records = metricRecords('cpu', 3)
            const value = await encodeMetricsPacket(TEST_RECORD_TYPE, 'zstandard', records)
            const result = await step({ message: createTestMessage({ value }), teamId: 7 })

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value.records).toEqual(records)
                expect(result.value.codec).toBe('zstandard')
                expect(result.value.schemaFingerprint).toBe(TEST_RECORD_TYPE.fingerprint('md5').toString('hex'))
            }
        })

        it('drops a null value', async () => {
            const result = await step({ message: createTestMessage({ value: null }), teamId: 7 })
            expectDrop(result, 'null_value')
        })

        it('sends an undecodable value to the DLQ', async () => {
            const result = await step({ message: createTestMessage({ value: Buffer.from('not avro') }), teamId: 7 })
            expect(isDlqResult(result)).toBe(true)
            if (isDlqResult(result)) {
                expect(result.reason).toBe('metrics_decode_failed')
                expect(result.error).toBeInstanceOf(Error)
            }
            expect(await counterValue(metricMessageDlqCounter, { reason: 'decode_failed', team_id: '7' })).toBe(1)
        })
    })

    describe('repackAndProduceMetricsStep', () => {
        let outputs: jest.Mocked<ReturnType<typeof createMockIngestionOutputs<MetricsOutput>>>
        const config = { maxRecordsPerPacket: 1_000_000, maxBytesUncompressedPerPacket: 50 * 1024 * 1024 }

        const makeInput = (teamId: number, records: MetricRecord[], headers: Record<string, string> = {}) => ({
            message: createTestMessage({
                headers: toHeaders({
                    token: `tok-${teamId}`,
                    bytes_uncompressed: String(records.length * 100),
                    record_count: String(records.length),
                    batch_uuid: `batch-${records[0]?.metric_name ?? 'empty'}`,
                    ...headers,
                }),
            }),
            token: `tok-${teamId}`,
            teamId,
            bytesUncompressed: records.length * 100,
            recordType: TEST_RECORD_TYPE,
            schemaFingerprint: TEST_RECORD_TYPE.fingerprint('md5').toString('hex'),
            codec: 'zstandard',
            records,
        })

        const producedTo = (output: string) =>
            outputs.produce.mock.calls.filter(([name]) => name === output).map(([, message]) => message)

        beforeEach(() => {
            outputs = createMockIngestionOutputs<MetricsOutput>()
        })

        it('groups by team, retention and schema', () => {
            const a = makeInput(1, metricRecords('a', 1), { 'retention-days': '30' })
            const b = makeInput(1, metricRecords('b', 1), { 'retention-days': '30' })
            const c = makeInput(1, metricRecords('c', 1), { 'retention-days': '7' })
            const d = makeInput(2, metricRecords('d', 1), { 'retention-days': '30' })
            expect(metricsRepackGroupKey(a)).toBe(metricsRepackGroupKey(b))
            expect(metricsRepackGroupKey(a)).not.toBe(metricsRepackGroupKey(c))
            expect(metricsRepackGroupKey(a)).not.toBe(metricsRepackGroupKey(d))
            expect(metricsRepackGroupKey(a)).not.toBe(metricsRepackGroupKey({ ...b, schemaFingerprint: 'other' }))
        })

        it("merges a team's packets into one produce and credits every member after the ack", async () => {
            const inputs = [
                makeInput(1, metricRecords('a', 2), { 'retention-days': '30' }),
                makeInput(1, metricRecords('b', 3)),
                makeInput(1, []),
            ]
            const results = await createRepackAndProduceMetricsStep(outputs, config)(inputs)

            expect(results).toHaveLength(inputs.length)
            expect(results.every(isOkResult)).toBe(true)
            const produced = producedTo(METRICS_OUTPUT)
            expect(produced).toHaveLength(1)
            expect(produced[0].key).toBeNull()
            expect(produced[0].headers).toEqual({
                token: 'tok-1',
                team_id: '1',
                'retention-days': '30',
                bytes_uncompressed: '500',
                bytes_compressed: String(produced[0].value!.length),
                record_count: '5',
                repacked_from: '2',
            })
            const decoded = await decodeMetricsPacket(produced[0].value!)
            expect(decoded.records).toEqual([...inputs[0].records, ...inputs[1].records])
            expect(decoded.codec).toBe('zstandard')
            expect(jest.mocked(recordMetricsIngested).mock.calls).toEqual([
                [1, 200, 2],
                [1, 300, 3],
            ])
        })

        it('starts a new packet when a cap would be exceeded and keeps capture-batch headers on single-member packets', async () => {
            const inputs = [
                makeInput(1, metricRecords('a', 2)),
                makeInput(1, metricRecords('b', 1)),
                makeInput(1, metricRecords('c', 2)),
            ]
            const results = await createRepackAndProduceMetricsStep(outputs, { ...config, maxRecordsPerPacket: 2 })(
                inputs
            )

            expect(results).toHaveLength(inputs.length)
            const produced = producedTo(METRICS_OUTPUT)
            expect(produced.map((m) => m.headers?.record_count)).toEqual(['2', '1', '2'])
            expect(produced.map((m) => m.headers?.batch_uuid)).toEqual(['batch-a_0', 'batch-b_0', 'batch-c_0'])
        })

        it('sends every member of a packet to the DLQ when its produce fails', async () => {
            outputs.produce.mockRejectedValueOnce(new Error('broker down'))
            const inputs = [makeInput(1, metricRecords('a', 1)), makeInput(1, metricRecords('b', 1))]
            const results = await createRepackAndProduceMetricsStep(outputs, config)(inputs)

            expect(results).toHaveLength(2)
            for (const result of results) {
                expect(isDlqResult(result)).toBe(true)
                if (isDlqResult(result)) {
                    expect(result.reason).toBe('metrics_produce_failed')
                }
            }
            expect(recordMetricsIngested).not.toHaveBeenCalled()
            expect(await counterValue(metricMessageDlqCounter, { reason: 'Error', team_id: '1' })).toBe(2)
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
