import { Message } from 'node-rdkafka'

import { parseKafkaHeaders } from '~/common/kafka/consumer'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { ChunkProcessingStep } from '~/ingestion/framework/builders'
import { PipelineResult, dlq, ok } from '~/ingestion/framework/results'

import { recordMetricsIngested } from './ingestion-otel-metrics'
import { metricMessageDlqCounter, metricsPacketsProducedCounter, metricsPacketsRepackedCounter } from './metrics'
import { DecodedMetricsPacket, encodeMetricsPacket } from './metrics-avro'
import { METRICS_OUTPUT, MetricsOutput } from './outputs/outputs'
import { MetricRecord } from './types'

export interface RepackMetricsConfig {
    maxRecordsPerPacket: number
    maxBytesUncompressedPerPacket: number
}

export interface RepackMetricsInput extends DecodedMetricsPacket {
    message: Message
    token: string
    teamId: number
    bytesUncompressed: number
}

/**
 * Packets only merge when ClickHouse would read the same headers from them and
 * the rows share one writer schema: `team_id` and `retention-days` feed the
 * Kafka table, and a schema change deploy can put two schema versions in one
 * batch.
 */
export function metricsRepackGroupKey(input: { teamId: number; schemaFingerprint: string; message: Message }): string {
    const retentionDays = parseKafkaHeaders(input.message.headers)['retention-days'] ?? ''
    return `${input.teamId}:${retentionDays}:${input.schemaFingerprint}`
}

interface Packet<T> {
    members: { index: number; value: T }[]
    records: MetricRecord[]
    bytesUncompressed: number
}

/**
 * Packs whole input packets into output packets in input order. A packet is
 * closed when the next input would push it over a cap; an input larger than a
 * cap on its own becomes a packet of one. Inputs are never split.
 */
function packInputs<T extends RepackMetricsInput>(values: T[], config: RepackMetricsConfig): Packet<T>[] {
    const packets: Packet<T>[] = []
    let current: Packet<T> | null = null

    values.forEach((value, index) => {
        if (value.records.length === 0) {
            return
        }
        const overflowsRecords = current && current.records.length + value.records.length > config.maxRecordsPerPacket
        const overflowsBytes =
            current && current.bytesUncompressed + value.bytesUncompressed > config.maxBytesUncompressedPerPacket
        if (!current || overflowsRecords || overflowsBytes) {
            current = { members: [], records: [], bytesUncompressed: 0 }
            packets.push(current)
        }
        current.members.push({ index, value })
        current.records.push(...value.records)
        current.bytesUncompressed += value.bytesUncompressed
    })

    return packets
}

const PER_CAPTURE_BATCH_HEADERS = ['batch_uuid', 'bytes_uncompressed_records', 'timestamps_overridden']

/**
 * Output headers start from the first member's headers (so `retention-days`
 * and anything else capture stamped survive), then the size headers are
 * recomputed for the merged payload. Headers that describe one capture batch
 * are only kept when the packet is that one batch.
 */
function mergedPacketHeaders<T extends RepackMetricsInput>(packet: Packet<T>, encoded: Buffer): Record<string, string> {
    const leader = packet.members[0].value
    const headers: Record<string, string> = { ...parseKafkaHeaders(leader.message.headers) }
    if (packet.members.length > 1) {
        for (const header of PER_CAPTURE_BATCH_HEADERS) {
            delete headers[header]
        }
    }
    return {
        ...headers,
        token: leader.token,
        team_id: leader.teamId.toString(),
        bytes_uncompressed: packet.bytesUncompressed.toString(),
        bytes_compressed: encoded.length.toString(),
        record_count: packet.records.length.toString(),
        repacked_from: packet.members.length.toString(),
    }
}

/**
 * Group chunk step (one team per chunk): merges the chunk's decoded packets
 * into as few output packets as the caps allow, encodes and produces them.
 * Every member of a packet shares its outcome, so a failed produce sends each
 * member's original message to the DLQ and no row is lost.
 */
export function createRepackAndProduceMetricsStep<T extends RepackMetricsInput>(
    outputs: IngestionOutputs<MetricsOutput>,
    config: RepackMetricsConfig
): ChunkProcessingStep<T, void> {
    return async function repackAndProduceMetricsStep(values) {
        const results: PipelineResult<void>[] = values.map(() => ok(undefined))
        const packets = packInputs(values, config)

        await Promise.all(
            packets.map(async (packet) => {
                const leader = packet.members[0].value
                const teamIdLabel = leader.teamId.toString()
                try {
                    const encoded = await encodeMetricsPacket(leader.recordType, leader.codec, packet.records)
                    await outputs.produce(METRICS_OUTPUT, {
                        value: encoded,
                        key: null,
                        headers: mergedPacketHeaders(packet, encoded),
                    })
                } catch (error) {
                    const errorName = error instanceof Error ? error.name : 'UnknownError'
                    metricMessageDlqCounter.inc({ reason: errorName, team_id: teamIdLabel }, packet.members.length)
                    for (const member of packet.members) {
                        results[member.index] = dlq('metrics_produce_failed', error)
                    }
                    return
                }

                metricsPacketsProducedCounter.inc({ team_id: teamIdLabel })
                metricsPacketsRepackedCounter.inc({ team_id: teamIdLabel }, packet.members.length)
                // Only after the ClickHouse-bound produce resolves — messages that
                // fail and route to the DLQ must not count as ingested.
                for (const member of packet.members) {
                    recordMetricsIngested(
                        member.value.teamId,
                        member.value.bytesUncompressed,
                        member.value.records.length
                    )
                }
            })
        )

        return results
    }
}
