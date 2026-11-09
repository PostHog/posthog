import { Message } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'
import { ChunkProcessingStep } from '~/ingestion/framework/builders'
import { PipelineResult, drop, ok } from '~/ingestion/framework/results'
import { ValueMatcher } from '~/types'

import { aggregateMetricRecords, isAggregatable } from './aggregate-metric-records'
import {
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

async function decodeInput<T extends AggregateMetricsInput>(value: T, index: number): Promise<DecodedInput | null> {
    try {
        const decoded = await decodeMetricRecords(value.message.value!)
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
        logger.warn('metrics_aggregation_decode_failed', { error: String(error), team_id: value.teamId })
        metricsAggregationSkippedCounter.inc({ reason: 'decode_error' })
        return null
    }
}

// Each message takes back at most as many points as it gave, so it stays under the producer size limit.
// The first message takes the size counters of the dropped messages so that the ingested totals stay the same.
async function aggregateMessages<T extends AggregateMetricsInput>(
    values: T[],
    inputs: DecodedInput[],
    results: PipelineResult<T>[]
): Promise<void> {
    const aggregatableCount = inputs.reduce((total, input) => total + input.aggregatable.length, 0)
    const aggregated = aggregateMetricRecords(inputs.flatMap((input) => input.aggregatable))
    metricsAggregationPointsCounter.inc({ stage: 'in' }, aggregatableCount)
    metricsAggregationPointsCounter.inc({ stage: 'out' }, aggregated.length)
    if (aggregated.length === aggregatableCount) {
        return
    }

    const recordsPerInput = inputs.map((input) => [
        ...input.passthrough,
        ...aggregated.splice(0, input.aggregatable.length),
    ])
    const encoded = await Promise.all(
        inputs.map((input, position) =>
            recordsPerInput[position].length === 0
                ? Promise.resolve(null)
                : encodeMetricRecords(input.decoded, recordsPerInput[position])
        )
    )

    const first = values[inputs[0].index]
    let bytesUncompressed = first.bytesUncompressed
    let recordCount = first.recordCount
    for (let position = 1; position < inputs.length; position++) {
        const { index } = inputs[position]
        const buffer = encoded[position]
        if (buffer === null) {
            bytesUncompressed += values[index].bytesUncompressed
            recordCount += values[index].recordCount
            results[index] = drop('metrics_aggregated_into_other_message')
        } else {
            results[index] = ok({ ...values[index], message: { ...values[index].message, value: buffer } })
        }
    }
    results[inputs[0].index] = ok({
        ...first,
        message: { ...first.message, value: encoded[0]! },
        bytesUncompressed,
        recordCount,
    })
}

// Merges only messages of one team and one source partition, because ClickHouse tracks freshness per
// source partition through a header that the produce step sets.
export function createAggregateMetricsStep<T extends AggregateMetricsInput>(
    isTeamEnabled: ValueMatcher<number>
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

        await Promise.all(
            [...groups.values()].map(async (indices) => {
                const decoded = await Promise.all(indices.map((index) => decodeInput(values[index], index)))
                const bySchema = new Map<string, DecodedInput[]>()
                for (const input of decoded) {
                    if (input === null || input.aggregatable.length === 0) {
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
            })
        )

        return results
    }
}
