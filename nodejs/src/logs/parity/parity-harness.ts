import { createHash } from 'crypto'
import { Message } from 'node-rdkafka'

import { MessageKey } from '~/common/kafka/producer'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { IngestionOutputMessage } from '~/common/outputs/types'
import { DependencyUnavailableError } from '~/common/utils/db/error'
import { parseJSON } from '~/common/utils/json-parse'

import { LogsIngestionFrameworkConsumer } from '../framework/logs-ingestion-framework-consumer'
import { TracesIngestionFrameworkConsumer } from '../framework/traces-ingestion-framework-consumer'
import { MESSAGE_KEYS } from '../log-pattern-mask'
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

const LibrdKafkaError = require('node-rdkafka/lib/error')
const { err2str } = require('node-rdkafka/librdkafka') as { err2str: (code: number) => string }

export function librdKafkaError(code: number, sync = false): Error {
    return LibrdKafkaError.create(sync ? code : new Error(err2str(code)))
}

function toError(spec: ParityError): Error {
    if (spec.kafka_code !== undefined) {
        return librdKafkaError(spec.kafka_code, spec.kafka_sync)
    }
    const cause = new Error(spec.message)
    cause.name = spec.name
    if (spec.dependency_unavailable) {
        return new DependencyUnavailableError(spec.message, 'parity', cause)
    }
    return cause
}

type CapturedMessage = { batch: number; output: string; message: IngestionOutputMessage }

class CapturingIngestionOutputs extends IngestionOutputs<string> {
    public readonly captured: CapturedMessage[] = []
    public producedCount = 0
    public currentBatch = 0
    private readonly remainingFaults: number[]

    constructor(
        private readonly scenario: ParityScenario,
        private readonly discard = false
    ) {
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
        this.producedCount += messages.length
        if (!this.discard) {
            for (const message of messages) {
                this.captured.push({ batch: this.currentBatch, output, message })
            }
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
        key: message.key === null ? null : Buffer.from(message.key),
        size: value?.length ?? 0,
        value,
        headers: message.headers.map(([key, headerValue]) => ({ [key]: Buffer.from(headerValue) })),
    }
}

/** Avro maps carry no order that ClickHouse reads, so keys are sorted. Avro arrays are ordered, so arrays keep their order. */
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
    // Read the container header directly to keep the schema JSON exactly as the writer emitted it.
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
    inputs: Map<string, { batch: number; index: number }>
): Promise<ParityValue> {
    if (value === null) {
        return { kind: 'null' }
    }
    // By bytes, not identity: a copy of the input is still a passthrough.
    const input = inputs.get(value.toString('base64'))
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
        const raw = value.toString('utf8')
        return { kind: 'json', raw, json: canonicalizeAvroValue(parseJSON(raw)) }
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

/** These follow concurrent message completion, so they are sorted. A histogram's bucket arrays are positional and keep their order. */
// Database 9, so a parity or benchmark run never flushes the keys a local stack keeps in database 0.
// nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
export const PARITY_REDIS_URL = 'redis://127.0.0.1:6379/9'

const UNORDERED_METRIC_ARRAYS = new Set([
    'resourceMetrics',
    'scopeMetrics',
    'metrics',
    'dataPoints',
    'attributes',
    'exemplars',
    'filteredAttributes',
])

function canonicalizeMetricPayload(payload: unknown): unknown {
    const sortArrays = (value: unknown, key?: string): unknown => {
        if (Array.isArray(value)) {
            const items = value.map((item) => sortArrays(item))
            return key !== undefined && UNORDERED_METRIC_ARRAYS.has(key) ? items.sort(compareCanonical) : items
        }
        if (value !== null && typeof value === 'object') {
            return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, sortArrays(v, k)]))
        }
        return value
    }
    return sortArrays(canonicalizeAvroValue(payload))
}

function indexInputs(scenario: ParityScenario): Map<string, { batch: number; index: number }> {
    const inputs = new Map<string, { batch: number; index: number }>()
    scenario.batches.forEach((batch, batchIndex) =>
        batch.forEach((message, index) => {
            if (message.value_b64 === null) {
                return
            }
            if (inputs.has(message.value_b64)) {
                throw new Error(
                    `scenario ${scenario.name} repeats an input value at batch ${batchIndex} index ${index}`
                )
            }
            inputs.set(message.value_b64, { batch: batchIndex, index })
        })
    )
    return inputs
}

export type ParityConsumerClasses = {
    logs: new (config: any, deps: any) => Pick<LogsIngestionConsumer, 'processKafkaBatch'>
    traces: new (config: any, deps: any) => Pick<LogsIngestionConsumer, 'processKafkaBatch'>
}

export const CURRENT_CLASSES: ParityConsumerClasses = { logs: LogsIngestionConsumer, traces: TracesIngestionConsumer }

export const FRAMEWORK_CLASSES: ParityConsumerClasses = {
    logs: LogsIngestionFrameworkConsumer,
    traces: TracesIngestionFrameworkConsumer,
}

export function buildParityConsumer(
    scenario: ParityScenario,
    options: { classes?: ParityConsumerClasses; discard?: boolean } = {}
) {
    const classes = options.classes ?? CURRENT_CLASSES
    const outputs = new CapturingIngestionOutputs(scenario, options.discard)
    const teamsById = new Map(scenario.teams.map((team) => [team.id, team]))
    const teamsByToken = new Map(scenario.teams.map((team) => [team.api_token, team]))
    const teamsIngested: number[][] = []
    const metricEmits: ParityExpected['metric_emits'] = []
    const usageRecords: (Omit<ParityExpected['usage_records'][number], 'record_group'> & { record_id: string })[] = []
    const quotaChecks = new Set<string>()
    const teamByIdFaultsLeft = new Map(
        Object.entries(scenario.team_by_id_faults).map(([teamId, fault]) => [Number(teamId), fault.times])
    )
    const patternFaultsLeft = new Map(
        Object.entries(scenario.pattern_keys_faults).map(([teamId, fault]) => [Number(teamId), fault.times])
    )

    // Rules compile once per team, as the production caches serve them, so a benchmark does not time compilation.
    const compiled = new Map<string, unknown>()
    const memo = <T>(key: string, build: () => T): T => {
        if (!compiled.has(key)) {
            compiled.set(key, build())
        }
        return compiled.get(key) as T
    }

    const teamManager = {
        getTeam: (id: number) => {
            const left = teamByIdFaultsLeft.get(id) ?? 0
            if (left > 0) {
                teamByIdFaultsLeft.set(id, left - 1)
                return Promise.reject(toError(scenario.team_by_id_faults[id]))
            }
            if (scenario.team_by_id_missing.includes(id)) {
                return Promise.resolve(null)
            }
            return Promise.resolve(teamsById.get(id) ?? null)
        },
        getTeamByToken: (token: string) => {
            const fault = scenario.team_lookup_faults[token]
            if (fault) {
                return Promise.reject(toError(fault))
            }
            return Promise.resolve(teamsByToken.get(token) ?? null)
        },
        setTeamsIngestedData: (ids: number[]) => {
            if (!options.discard) {
                teamsIngested.push([...ids])
            }
            return Promise.resolve()
        },
    }

    const deps: TracesIngestionConsumerDeps = {
        teamManager: teamManager as unknown as LogsIngestionConsumerDeps['teamManager'],
        quotaLimiting: {
            isTeamTokenQuotaLimited: (token: string, resource: string) => {
                if (!options.discard) {
                    quotaChecks.add(JSON.stringify([token, resource]))
                }
                return Promise.resolve(scenario.quota_limited_tokens.includes(token))
            },
        } as unknown as LogsIngestionConsumerDeps['quotaLimiting'],
        outputs: outputs as unknown as LogsIngestionConsumerDeps['outputs'],
        usageBatch: {
            add: (teamId: number, metric: string, recordId: string, quantity = 1, unit?: string) => {
                if (options.discard) {
                    return
                }
                usageRecords.push({
                    batch: outputs.currentBatch,
                    team_id: teamId,
                    metric,
                    quantity,
                    unit: unit ?? '',
                    record_id: recordId,
                })
            },
            flush: () => Promise.resolve(),
        } as unknown as LogsIngestionConsumerDeps['usageBatch'],
        dependencyRetry: { retryCount: 2, initialRetryDelayMs: 1 },
        samplingRulesCache: {
            getCompiledRuleSet: (teamId: number) =>
                Promise.resolve(
                    memo(`sampling:${teamId}`, () =>
                        compileRuleSet((scenario.sampling_rules[teamId] ?? []) as SamplingRuleRow[])
                    )
                ),
        } as unknown as LogsIngestionConsumerDeps['samplingRulesCache'],
        retentionRulesCache: {
            getCompiledRuleSet: (teamId: number, source: string) =>
                Promise.resolve(
                    memo(`retention:${teamId}:${source}`, () =>
                        compileRetentionRuleSet(
                            (scenario.retention_rules[teamId]?.[source] ?? []) as RetentionRuleRow[]
                        )
                    )
                ),
        } as unknown as LogsIngestionConsumerDeps['retentionRulesCache'],
        metricRulesCache: {
            getCompiledRules: (teamId: number) => {
                const fault = scenario.metric_rules_faults[teamId]
                if (fault) {
                    return Promise.reject(toError(fault))
                }
                return Promise.resolve(
                    memo(`metrics:${teamId}`, () =>
                        compileMetricRules((scenario.metric_rules[teamId] ?? []) as MetricRuleRow[])
                    )
                )
            },
        } as unknown as LogsIngestionConsumerDeps['metricRulesCache'],
        metricsEmitter: {
            emit: (token: string, teamId: number, payload: Record<string, unknown>) => {
                if (scenario.metric_emit_faults.includes(teamId)) {
                    return Promise.reject(new Error('metric emit failed'))
                }
                if (!options.discard) {
                    metricEmits.push({ token, team_id: teamId, payload })
                }
                return Promise.resolve(true)
            },
        } as unknown as LogsIngestionConsumerDeps['metricsEmitter'],
        patternMessageKeysCache: {
            getMessageKeys: (teamId: number) => {
                const left = patternFaultsLeft.get(teamId) ?? 0
                if (left > 0) {
                    patternFaultsLeft.set(teamId, left - 1)
                    return Promise.reject(toError(scenario.pattern_keys_faults[teamId]))
                }
                // Production returns the default keys for a team without a row.
                return Promise.resolve(scenario.pattern_message_keys[teamId] ?? MESSAGE_KEYS)
            },
        } as unknown as LogsIngestionConsumerDeps['patternMessageKeysCache'],
        internalSourcePolicies:
            scenario.internal_source_policies &&
            Object.fromEntries(
                Object.entries(scenario.internal_source_policies).map(([source, policy]) => [
                    source,
                    { ...policy, serviceName: `posthog-internal-${source}` },
                ])
            ),
        tracingConfigCache: {
            getRetentionDays: (teamId: number) => Promise.resolve(scenario.traces_retention_days[teamId] ?? 30),
        } as unknown as TracesIngestionConsumerDeps['tracingConfigCache'],
    }
    for (const dep of scenario.omit_deps) {
        delete deps[dep]
    }

    const config = { ...scenario.config, LOGS_REDIS_HOST: PARITY_REDIS_URL, TRACES_REDIS_HOST: PARITY_REDIS_URL } as any
    const consumer = scenario.consumer === 'traces' ? new classes.traces(config, deps) : new classes.logs(config, deps)
    return { consumer, outputs, teamsIngested, metricEmits, usageRecords, quotaChecks }
}

/** The caller empties `PARITY_REDIS_URL` before the call. */
export async function runParityScenario(
    scenario: ParityScenario,
    setClock: (nowMs: number) => void,
    classes: ParityConsumerClasses = CURRENT_CLASSES
): Promise<ParityExpected> {
    const { consumer, outputs, teamsIngested, metricEmits, usageRecords, quotaChecks } = buildParityConsumer(scenario, {
        classes,
    })
    const inputs = indexInputs(scenario)
    const batchResults: ParityExpected['batches'] = []
    for (let batchIndex = 0; batchIndex < scenario.batches.length; batchIndex++) {
        outputs.currentBatch = batchIndex
        setClock(scenario.batch_now_ms[batchIndex])
        const messages = scenario.batches[batchIndex].map(toKafkaMessage)
        try {
            const { backgroundTask } = await consumer.processKafkaBatch(messages)
            await backgroundTask
            batchResults.push({ error: null })
        } catch (error) {
            batchResults.push({ error: error instanceof Error ? error.name : String(error) })
        }
    }

    const canonicalOutputs: ParityOutputMessage[] = []
    for (const { batch, output, message } of outputs.captured) {
        canonicalOutputs.push({
            batch,
            output,
            key: message.key === null || message.key === undefined ? null : String(message.key),
            headers: sortedHeaders(message.headers),
            value: await canonicalizeValue(output, message.value, inputs),
        })
    }
    canonicalOutputs.sort(compareCanonical)

    usageRecords.sort((a, b) => compareCanonical({ ...a, record_id: '' }, { ...b, record_id: '' }))
    const groups = new Map<string, number>()
    const canonicalUsage = usageRecords.map(({ record_id, ...rest }) => {
        if (!groups.has(record_id)) {
            groups.set(record_id, groups.size)
        }
        return { ...rest, record_group: groups.get(record_id)! }
    })

    const canonicalEmits = metricEmits.map((emit) => ({ ...emit, payload: canonicalizeMetricPayload(emit.payload) }))
    canonicalEmits.sort(compareCanonical)

    return {
        batches: batchResults,
        outputs: canonicalOutputs,
        metric_emits: canonicalEmits,
        usage_records: canonicalUsage,
        teams_ingested: teamsIngested,
        quota_checks: [...quotaChecks].sort().map((pair) => parseJSON(pair) as [string, string]),
    }
}
