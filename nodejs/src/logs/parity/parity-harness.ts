import { createHash } from 'crypto'
import { Message } from 'node-rdkafka'

import { MessageKey } from '~/common/kafka/producer'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { IngestionOutputMessage } from '~/common/outputs/types'
import { DependencyUnavailableError } from '~/common/utils/db/error'
import { parseJSON } from '~/common/utils/json-parse'

import { getDefaultLogsIngestionConsumerConfig, getDefaultTracesIngestionConsumerConfig } from '../config'
import { decodeLogRecords } from '../log-record-avro'
import { LogsIngestionConsumer, LogsIngestionConsumerDeps } from '../logs-ingestion-consumer'
import { type MetricRuleRow, compileMetricRules } from '../metrics-rules/compile-metric-rules'
import { type RetentionRuleRow, compileRetentionRuleSet } from '../retention/compile-retention-rules'
import { type SamplingRuleRow, compileRuleSet } from '../sampling/compile-rules'
import { TracesIngestionConsumer, TracesIngestionConsumerDeps } from '../traces-ingestion-consumer'
import type {
    ParityError,
    ParityExpected,
    ParityMessage,
    ParityOutputMessage,
    ParityScenario,
    ParityValue,
} from './parity-types'

function toError(spec: ParityError): Error {
    const cause = new Error(spec.message)
    cause.name = spec.name
    if (spec.dependency_unavailable) {
        return new DependencyUnavailableError(spec.message, 'parity', cause)
    }
    return cause
}

type CapturedMessage = { output: string; message: IngestionOutputMessage }

/** Records every message the consumer hands to an output, and fails the ones the scenario names. */
class CapturingIngestionOutputs extends IngestionOutputs<string> {
    public readonly captured: CapturedMessage[] = []
    private readonly remainingFaults: number[]

    constructor(private readonly scenario: ParityScenario) {
        super({})
        this.remainingFaults = scenario.produce_faults.map((fault) => fault.times)
    }

    private faultFor(output: string, message: IngestionOutputMessage): Error | null {
        for (let i = 0; i < this.scenario.produce_faults.length; i++) {
            const fault = this.scenario.produce_faults[i]
            if (fault.output !== output || this.remainingFaults[i] <= 0) {
                continue
            }
            if (fault.team_id !== undefined && message.headers?.team_id !== fault.team_id) {
                continue
            }
            this.remainingFaults[i]--
            return toError(fault.error)
        }
        return null
    }

    override async produce(output: string, message: IngestionOutputMessage & { key: MessageKey }): Promise<void> {
        await this.queueMessages(output, [message])
    }

    override queueMessages(output: string, messages: IngestionOutputMessage[]): Promise<void> {
        for (const message of messages) {
            const fault = this.faultFor(output, message)
            if (fault) {
                return Promise.reject(fault)
            }
        }
        for (const message of messages) {
            this.captured.push({ output, message })
        }
        return Promise.resolve()
    }
}

export function toKafkaMessage(message: ParityMessage): Message {
    const value = message.value_b64 === null ? null : Buffer.from(message.value_b64, 'base64')
    return {
        topic: message.topic,
        partition: message.partition,
        offset: message.offset,
        timestamp: message.timestamp,
        key: null,
        size: value?.length ?? 0,
        value,
        headers: message.headers.map(([key, headerValue]) => ({ [key]: Buffer.from(headerValue) })),
    }
}

/**
 * Canonical JSON for a decoded Avro value: bytes become `{ $bytes: hex }`, and object keys are
 * sorted. Avro maps carry no order that ClickHouse reads, and two encoders may write them in
 * different orders.
 */
export function canonicalizeAvroValue(value: unknown): unknown {
    if (Buffer.isBuffer(value)) {
        return { $bytes: value.toString('hex') }
    }
    if (Array.isArray(value)) {
        return value.map(canonicalizeAvroValue)
    }
    if (value !== null && typeof value === 'object') {
        const out: Record<string, unknown> = {}
        for (const key of Object.keys(value).sort()) {
            out[key] = canonicalizeAvroValue((value as Record<string, unknown>)[key])
        }
        return out
    }
    return value
}

function readContainerSchemaAndCodec(buffer: Buffer): { schema: unknown; codec: string } | null {
    // An Avro object container header is the magic, then a metadata map of avro.schema and avro.codec.
    // Reading it directly keeps the schema JSON exactly as the writer emitted it.
    if (buffer.length < 4 || buffer.subarray(0, 4).toString('latin1') !== 'Obj\u0001') {
        return null
    }
    let offset = 4
    const readLong = (): number => {
        let n = 0
        let shift = 0
        let byte: number
        do {
            byte = buffer[offset++]
            n += (byte & 0x7f) * 2 ** shift
            shift += 7
        } while (byte & 0x80)
        return n % 2 === 0 ? n / 2 : -(n + 1) / 2
    }
    const meta: Record<string, string> = {}
    for (;;) {
        let count = readLong()
        if (count === 0) {
            break
        }
        if (count < 0) {
            count = -count
            readLong()
        }
        for (let i = 0; i < count; i++) {
            const keyLength = readLong()
            const key = buffer.subarray(offset, offset + keyLength).toString('utf8')
            offset += keyLength
            const valueLength = readLong()
            meta[key] = buffer.subarray(offset, offset + valueLength).toString('utf8')
            offset += valueLength
        }
    }
    return { schema: parseJSON(meta['avro.schema']), codec: meta['avro.codec'] ?? 'null' }
}

async function canonicalizeValue(
    output: string,
    value: Buffer | null,
    inputs: Map<Buffer, { batch: number; index: number }>
): Promise<ParityValue> {
    if (value === null) {
        return { kind: 'null' }
    }
    const input = inputs.get(value)
    if (input) {
        return { kind: 'passthrough', ...input }
    }
    if (output === 'logs') {
        const header = readContainerSchemaAndCodec(value)
        if (header) {
            const [, , records] = await decodeLogRecords(value)
            return {
                kind: 'avro',
                schema: header.schema,
                codec: header.codec,
                records: records.map(canonicalizeAvroValue),
            }
        }
    }
    if (output === 'app_metrics') {
        return { kind: 'json', json: canonicalizeAvroValue(parseJSON(value.toString('utf8'))) }
    }
    return { kind: 'bytes', sha256: createHash('sha256').update(value).digest('hex'), length: value.length }
}

function sortedHeaders(headers: Record<string, string> | undefined): Record<string, string> {
    const out: Record<string, string> = {}
    for (const key of Object.keys(headers ?? {}).sort()) {
        out[key] = headers![key]
    }
    return out
}

function compareCanonical(a: unknown, b: unknown): number {
    const left = JSON.stringify(a)
    const right = JSON.stringify(b)
    return left < right ? -1 : left > right ? 1 : 0
}

export type ParityConsumer = Pick<LogsIngestionConsumer, 'processKafkaBatch'>

/**
 * Runs one scenario through the consumer and returns its canonical outputs. The caller pins the
 * clock to `scenario.now_ms` and empties Redis before the call.
 */
export async function runParityScenario(scenario: ParityScenario): Promise<ParityExpected> {
    const outputs = new CapturingIngestionOutputs(scenario)
    const teamsById = new Map(scenario.teams.map((team) => [team.id, team]))
    const teamsByToken = new Map(scenario.teams.map((team) => [team.api_token, team]))
    const teamsIngested: number[][] = []
    const metricEmits: ParityExpected['metric_emits'] = []
    const usageRecords: ParityExpected['usage_records'] = []

    const teamManager = {
        getTeam: (id: number) => Promise.resolve(teamsById.get(id) ?? null),
        getTeamByToken: (token: string) => {
            const fault = scenario.team_lookup_faults[token]
            if (fault) {
                return Promise.reject(toError(fault))
            }
            return Promise.resolve(teamsByToken.get(token) ?? null)
        },
        setTeamsIngestedData: (ids: number[]) => {
            teamsIngested.push([...ids])
            return Promise.resolve()
        },
    }

    const deps: TracesIngestionConsumerDeps = {
        teamManager: teamManager as unknown as LogsIngestionConsumerDeps['teamManager'],
        quotaLimiting: {
            isTeamTokenQuotaLimited: (token: string) => Promise.resolve(scenario.quota_limited_tokens.includes(token)),
        } as unknown as LogsIngestionConsumerDeps['quotaLimiting'],
        outputs: outputs as unknown as LogsIngestionConsumerDeps['outputs'],
        usageBatch: {
            add: (teamId: number, metric: string, _recordId: string, quantity = 1, unit?: string) => {
                usageRecords.push({ team_id: teamId, metric, quantity, unit: unit ?? '' })
            },
            flush: () => Promise.resolve(),
        } as unknown as LogsIngestionConsumerDeps['usageBatch'],
        dependencyRetry: { retryCount: 2, initialRetryDelayMs: 1 },
        samplingRulesCache: {
            getCompiledRuleSet: (teamId: number) =>
                Promise.resolve(compileRuleSet((scenario.sampling_rules[teamId] ?? []) as SamplingRuleRow[])),
        } as unknown as LogsIngestionConsumerDeps['samplingRulesCache'],
        retentionRulesCache: {
            getCompiledRuleSet: (teamId: number, source: string) =>
                Promise.resolve(
                    compileRetentionRuleSet((scenario.retention_rules[teamId]?.[source] ?? []) as RetentionRuleRow[])
                ),
        } as unknown as LogsIngestionConsumerDeps['retentionRulesCache'],
        metricRulesCache: {
            getCompiledRules: (teamId: number) =>
                Promise.resolve(compileMetricRules((scenario.metric_rules[teamId] ?? []) as MetricRuleRow[])),
        } as unknown as LogsIngestionConsumerDeps['metricRulesCache'],
        metricsEmitter: {
            emit: (token: string, teamId: number, payload: Record<string, unknown>) => {
                metricEmits.push({ token, team_id: teamId, payload })
                return Promise.resolve(true)
            },
        } as unknown as LogsIngestionConsumerDeps['metricsEmitter'],
        patternMessageKeysCache: {
            getMessageKeys: (teamId: number) => Promise.resolve(scenario.pattern_message_keys[teamId] ?? []),
        } as unknown as LogsIngestionConsumerDeps['patternMessageKeysCache'],
        internalSourcePolicies: scenario.internal_source_policies,
        tracingConfigCache: {
            getRetentionDays: (teamId: number) => Promise.resolve(scenario.traces_retention_days[teamId] ?? 30),
        } as unknown as TracesIngestionConsumerDeps['tracingConfigCache'],
    }
    // Absent keys must stay absent, so the consumer sees the same optional deps as production.
    if (Object.keys(scenario.pattern_message_keys).length === 0) {
        delete deps.patternMessageKeysCache
    }

    const config = {
        ...getDefaultLogsIngestionConsumerConfig(),
        ...getDefaultTracesIngestionConsumerConfig(),
        REDIS_URL: 'redis://127.0.0.1:6379',
        REDIS_POOL_MIN_SIZE: 1,
        REDIS_POOL_MAX_SIZE: 3,
        LOGS_REDIS_TLS: false,
        TRACES_REDIS_TLS: false,
        LOGS_LIMITER_ENABLED_TEAMS: '*',
        TRACES_LIMITER_ENABLED_TEAMS: '*',
        ...scenario.config,
    }

    const consumer: ParityConsumer =
        scenario.consumer === 'traces'
            ? new TracesIngestionConsumer(config as any, deps)
            : new LogsIngestionConsumer(config as any, deps)

    const inputs = new Map<Buffer, { batch: number; index: number }>()
    const batchResults: ParityExpected['batches'] = []
    for (let batchIndex = 0; batchIndex < scenario.batches.length; batchIndex++) {
        const messages = scenario.batches[batchIndex].map((message, index) => {
            const kafkaMessage = toKafkaMessage(message)
            if (kafkaMessage.value) {
                inputs.set(kafkaMessage.value, { batch: batchIndex, index })
            }
            return kafkaMessage
        })
        try {
            const { backgroundTask } = await consumer.processKafkaBatch(messages)
            await backgroundTask
            batchResults.push({ error: null })
        } catch (error) {
            batchResults.push({ error: error instanceof Error ? error.name : String(error) })
        }
    }

    const canonicalOutputs: ParityOutputMessage[] = []
    for (const { output, message } of outputs.captured) {
        const headers = sortedHeaders(message.headers)
        canonicalOutputs.push({
            output,
            key: message.key === null || message.key === undefined ? null : String(message.key),
            headers,
            value: await canonicalizeValue(output, message.value, inputs),
        })
    }
    canonicalOutputs.sort(compareCanonical)
    usageRecords.sort(compareCanonical)
    const canonicalEmits = metricEmits.map((emit) => ({ ...emit, payload: canonicalizeAvroValue(emit.payload) }))
    canonicalEmits.sort(compareCanonical)

    return {
        batches: batchResults,
        outputs: canonicalOutputs,
        metric_emits: canonicalEmits,
        usage_records: usageRecords,
        teams_ingested: teamsIngested.map((ids) => [...ids].sort((a, b) => a - b)),
    }
}
