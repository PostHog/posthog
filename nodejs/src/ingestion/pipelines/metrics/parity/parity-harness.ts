import { createHash } from 'crypto'
import { Message } from 'node-rdkafka'

import { DependencyUnavailableError, MessageSizeTooLarge } from '~/common/utils/db/error'
import { parseJSON } from '~/common/utils/json-parse'
import { getDefaultMetricsIngestionConsumerConfig } from '~/ingestion/pipelines/metrics/config'
import {
    MetricsPipelineConsumer,
    MetricsPipelineConsumerDeps,
} from '~/ingestion/pipelines/metrics/metrics-pipeline-consumer'
import { CapturingIngestionOutputs, indexInputs, toKafkaMessage } from '~/logs/parity/parity-harness'

import type {
    MetricsParityError,
    MetricsParityExpected,
    MetricsParityOutputMessage,
    MetricsParityScenario,
    MetricsParityValue,
} from './parity-types'

// Database 9, so a parity run never flushes the keys a local stack keeps in database 0.
// nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
export const PARITY_REDIS_URL = 'redis://127.0.0.1:6379/9'

const ISO_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/

export function toError(spec: MetricsParityError): Error {
    const cause = new Error(spec.message)
    switch (spec.kind) {
        case 'dependency_unavailable':
            return new DependencyUnavailableError(spec.message, 'parity', cause)
        case 'message_size_too_large':
            return new MessageSizeTooLarge(spec.message, cause)
        case 'non_retriable':
            return Object.assign(cause, { isRetriable: false })
        case 'error':
            return cause
    }
}

function compareCanonical(a: unknown, b: unknown): number {
    const left = JSON.stringify(a)
    const right = JSON.stringify(b)
    return left < right ? -1 : left > right ? 1 : 0
}

function sortKeys(value: unknown): unknown {
    if (Array.isArray(value)) {
        return value.map(sortKeys)
    }
    if (value !== null && typeof value === 'object') {
        const out: Record<string, unknown> = {}
        for (const key of Object.keys(value).sort()) {
            out[key] = sortKeys((value as Record<string, unknown>)[key])
        }
        return out
    }
    return value
}

function canonicalHeaders(headers: Record<string, string> | undefined): Record<string, string> {
    const out: Record<string, string> = {}
    for (const key of Object.keys(headers ?? {}).sort()) {
        const value = headers![key]
        out[key] = key === 'dlq_timestamp' && ISO_TIMESTAMP.test(value) ? '<iso>' : value
    }
    return out
}

function canonicalValue(
    output: string,
    value: Buffer | null,
    inputs: Map<string, { batch: number; index: number }>
): MetricsParityValue {
    if (value === null) {
        return { kind: 'null' }
    }
    const input = inputs.get(value.toString('base64'))
    if (input) {
        return { kind: 'passthrough', ...input }
    }
    if (output === 'app_metrics') {
        const raw = value.toString('utf8')
        return { kind: 'json', raw, json: sortKeys(parseJSON(raw)) }
    }
    return { kind: 'bytes', sha256: createHash('sha256').update(value).digest('hex'), length: value.length }
}

/** The caller empties `PARITY_REDIS_URL` before the call, and mocks `KafkaConsumerV2`, which the consumer constructs. */
export async function runMetricsParityScenario(
    scenario: MetricsParityScenario,
    setClock: (nowMs: number) => void
): Promise<MetricsParityExpected> {
    const outputs = new CapturingIngestionOutputs(scenario.produce_faults, toError)
    const teamsByToken = new Map(scenario.teams.map((team) => [team.api_token, team]))
    const teamsById = new Map(scenario.teams.map((team) => [team.id, team]))
    const lookupFaultsLeft = new Map(
        Object.entries(scenario.team_lookup_faults).map(([token, fault]) => [token, fault.times])
    )
    const teamsIngested: number[][] = []
    const usageRecords: MetricsParityExpected['usage_records'] = []
    const quotaChecks = new Set<string>()

    const deps = {
        teamManager: {
            getTeam: (id: number) => Promise.resolve(teamsById.get(id) ?? null),
            getTeamByToken: (token: string) => {
                const left = lookupFaultsLeft.get(token) ?? 0
                if (left > 0) {
                    lookupFaultsLeft.set(token, left - 1)
                    return Promise.reject(toError(scenario.team_lookup_faults[token]))
                }
                return Promise.resolve(teamsByToken.get(token) ?? null)
            },
            setTeamsIngestedData: (ids: number[]) => {
                teamsIngested.push([...ids].sort((a, b) => a - b))
                return Promise.resolve()
            },
        },
        quotaLimiting: {
            isTeamTokenQuotaLimited: (token: string, resource: string) => {
                quotaChecks.add(JSON.stringify([token, resource]))
                return Promise.resolve(scenario.quota_limited_tokens.includes(token))
            },
        },
        outputs,
        usageBatch: {
            add: (
                teamId: number,
                usageKey: string,
                recordId: string,
                quantity: number,
                unit: string,
                timestampMs?: number
            ) => {
                usageRecords.push({
                    batch: outputs.currentBatch,
                    team_id: teamId,
                    usage_key: usageKey,
                    record_id: recordId,
                    quantity,
                    unit,
                    timestamp_ms: timestampMs ?? null,
                })
            },
            flush: () => Promise.resolve([]),
        },
    } as unknown as MetricsPipelineConsumerDeps

    const config = {
        ...getDefaultMetricsIngestionConsumerConfig(),
        ...scenario.config,
        METRICS_REDIS_HOST: PARITY_REDIS_URL,
    } as any
    const consumer = new MetricsPipelineConsumer(config, deps)
    const inputs = indexInputs(scenario)

    const batchResults: MetricsParityExpected['batches'] = []
    for (let batchIndex = 0; batchIndex < scenario.batches.length; batchIndex++) {
        outputs.currentBatch = batchIndex
        setClock(scenario.batch_now_ms[batchIndex])
        const messages: Message[] = scenario.batches[batchIndex].map(toKafkaMessage)
        try {
            const { backgroundTask } = await consumer.handleKafkaBatch(messages)
            await backgroundTask
            batchResults.push({ error: null })
        } catch (error) {
            batchResults.push({ error: error instanceof Error ? error.name : String(error) })
        }
    }

    const canonicalOutputs: MetricsParityOutputMessage[] = outputs.captured.map(({ batch, output, message }) => ({
        batch,
        output,
        key: message.key === null || message.key === undefined ? null : String(message.key),
        headers: canonicalHeaders(message.headers),
        value: canonicalValue(output, message.value, inputs),
    }))
    canonicalOutputs.sort(compareCanonical)
    usageRecords.sort(compareCanonical)

    return {
        batches: batchResults,
        outputs: canonicalOutputs,
        usage_records: usageRecords,
        teams_ingested: teamsIngested,
        quota_checks: [...quotaChecks].sort().map((pair) => parseJSON(pair) as [string, string]),
    }
}
