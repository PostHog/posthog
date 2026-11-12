import { Message } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'
import { ChunkProcessingStep } from '~/ingestion/framework/builders'
import { PipelineResult, PipelineResultType, drop, ok } from '~/ingestion/framework/results'
import { ValueMatcher } from '~/types'

import { aggregateMetricRecords, isAggregatable } from './aggregate-metric-records'
import {
    DecodedBytesLimitError,
    DecodedMetricRecords,
    MetricRecord,
    decodeMetricRecords,
    encodeMetricRecords,
    isSupportedCodec,
} from './metric-record-avro'
import { metricsAggregationPointsCounter, metricsAggregationSkippedCounter } from './metrics'

export interface AggregateMetricsInput {
    message: Message
    teamId: number
    bytesUncompressed: number
    recordCount: number
}

interface DecodedInput {
    index: number
    decoded: DecodedMetricRecords
    passthrough: MetricRecord[]
    aggregatable: MetricRecord[]
}

async function decodeInput<T extends AggregateMetricsInput>(
    value: T,
    index: number,
    maxDecodedBytes: number
): Promise<DecodedInput | null> {
    try {
        const decoded = await decodeMetricRecords(value.message.value!, maxDecodedBytes)
        if (!isSupportedCodec(decoded.codec)) {
            metricsAggregationSkippedCounter.inc({ reason: 'unsupported_codec' })
            return null
        }
        const passthrough: MetricRecord[] = []
        const aggregatable: MetricRecord[] = []
        for (const record of decoded.records) {
            ;(isAggregatable(record) ? aggregatable : passthrough).push(record)
        }
        return { index, decoded, passthrough, aggregatable }
    } catch (error) {
        if (error instanceof DecodedBytesLimitError) {
            metricsAggregationSkippedCounter.inc({ reason: 'decoded_bytes_limit' })
            return null
        }
        logger.warn('metrics_aggregation_decode_failed', { error: String(error), team_id: value.teamId })
        metricsAggregationSkippedCounter.inc({ reason: 'decode_error' })
        return null
    }
}

const MAX_CHUNK_BYTES_UNCOMPRESSED = 32 * 1024 * 1024
export const MAX_CHUNK_DECODED_BYTES = 64 * 1024 * 1024

function encodedSize(input: DecodedInput, record: MetricRecord): number {
    return input.decoded.type.toBuffer(record).length
}

// No output message grows past the largest input message, which the producer already accepted.
async function aggregateMessages<T extends AggregateMetricsInput>(
    values: T[],
    inputs: DecodedInput[],
    results: PipelineResult<T>[]
): Promise<void> {
    const aggregatableCount = inputs.reduce((total, input) => total + input.aggregatable.length, 0)
    const aggregated = aggregateMetricRecords(inputs.flatMap((input) => input.aggregatable))
    metricsAggregationPointsCounter.inc({ stage: 'in' }, aggregatableCount)
    if (aggregated.length === aggregatableCount) {
        metricsAggregationPointsCounter.inc({ stage: 'out' }, aggregatableCount)
        return
    }

    const passthroughBytes = inputs.map((input) =>
        input.passthrough.reduce((total, record) => total + encodedSize(input, record), 0)
    )
    const budget = Math.max(
        ...inputs.map(
            (input, position) =>
                passthroughBytes[position] +
                input.aggregatable.reduce((total, record) => total + encodedSize(input, record), 0)
        )
    )
    const recordsPerInput = inputs.map((input) => [...input.passthrough])
    const usedBytes = [...passthroughBytes]
    let position = 0
    for (const record of aggregated) {
        const size = encodedSize(inputs[0], record)
        while (position < inputs.length - 1 && usedBytes[position] + size > budget) {
            position++
        }
        recordsPerInput[position].push(record)
        usedBytes[position] += size
    }
    // A merged histogram can encode larger than its inputs, so the last message can pass the budget.
    if (usedBytes[usedBytes.length - 1] > budget) {
        metricsAggregationSkippedCounter.inc({ reason: 'output_too_large' }, inputs.length)
        metricsAggregationPointsCounter.inc({ stage: 'out' }, aggregatableCount)
        return
    }
    metricsAggregationPointsCounter.inc({ stage: 'out' }, aggregated.length)

    const encoded = await Promise.all(
        inputs.map((input, position) =>
            recordsPerInput[position].length === 0
                ? Promise.resolve(null)
                : encodeMetricRecords(input.decoded, recordsPerInput[position])
        )
    )

    // Moving the counters of dropped messages keeps the ingested usage totals unchanged.
    const survivor = encoded.findIndex((buffer) => buffer !== null)
    let bytesUncompressed = 0
    let recordCount = 0
    inputs.forEach(({ index }, position) => {
        const buffer = encoded[position]
        if (buffer === null) {
            bytesUncompressed += values[index].bytesUncompressed
            recordCount += values[index].recordCount
            results[index] = drop('metrics_aggregated_into_other_message')
        } else {
            results[index] = ok({ ...values[index], message: { ...values[index].message, value: buffer } })
        }
    })
    const survivorResult = results[inputs[survivor].index]
    if (survivorResult.type === PipelineResultType.OK) {
        survivorResult.value.bytesUncompressed += bytesUncompressed
        survivorResult.value.recordCount += recordCount
    }
}

// Rows can expand far past their request size, so decoded bytes, not request bytes, bound memory.
async function aggregateChunk<T extends AggregateMetricsInput>(
    values: T[],
    indices: number[],
    results: PipelineResult<T>[],
    maxDecodedBytes: number
): Promise<void> {
    const decoded: DecodedInput[] = []
    let remaining = maxDecodedBytes
    for (const index of indices) {
        const input = await decodeInput(values[index], index, remaining)
        if (input === null) {
            continue
        }
        remaining -= input.decoded.decodedBytes
        decoded.push(input)
    }
    const bySchema = new Map<string, DecodedInput[]>()
    for (const input of decoded) {
        if (input.aggregatable.length === 0) {
            continue
        }
        const schema = input.decoded.meta['avro.schema']?.toString() ?? ''
        const key = `${input.decoded.codec}:${schema}`
        const inputs = bySchema.get(key)
        if (inputs) {
            inputs.push(input)
        } else {
            bySchema.set(key, [input])
        }
    }
    for (const inputs of bySchema.values()) {
        try {
            await aggregateMessages(values, inputs, results)
        } catch (error) {
            logger.error('metrics_aggregation_encode_failed', { error: String(error) })
            metricsAggregationSkippedCounter.inc({ reason: 'encode_error' }, inputs.length)
        }
    }
}

function splitByBytes<T extends AggregateMetricsInput>(values: T[], indices: number[]): number[][] {
    const chunks: number[][] = []
    let chunk: number[] = []
    let chunkBytes = 0
    for (const index of indices) {
        const bytes = values[index].bytesUncompressed
        if (chunk.length > 0 && chunkBytes + bytes > MAX_CHUNK_BYTES_UNCOMPRESSED) {
            chunks.push(chunk)
            chunk = []
            chunkBytes = 0
        }
        chunk.push(index)
        chunkBytes += bytes
    }
    if (chunk.length > 0) {
        chunks.push(chunk)
    }
    return chunks
}

// Merges only messages of one team and one source partition, because ClickHouse tracks freshness per
// source partition through a header that the produce step sets.
export function createAggregateMetricsStep<T extends AggregateMetricsInput>(
    isTeamEnabled: ValueMatcher<number>,
    maxDecodedBytesPerChunk = MAX_CHUNK_DECODED_BYTES
): ChunkProcessingStep<T, T> {
    return async function aggregateMetricsStep(values) {
        const results: PipelineResult<T>[] = values.map((value) => ok(value))

        const groups = new Map<string, number[]>()
        values.forEach((value, index) => {
            if (value.message.value === null || !isTeamEnabled(value.teamId)) {
                return
            }
            const key = `${value.teamId}:${value.message.topic}:${value.message.partition}`
            const group = groups.get(key)
            if (group) {
                group.push(index)
            } else {
                groups.set(key, [index])
            }
        })

        for (const indices of groups.values()) {
            for (const chunk of splitByBytes(values, indices)) {
                await aggregateChunk(values, chunk, results, maxDecodedBytesPerChunk)
            }
        }

        return results
    }
}
