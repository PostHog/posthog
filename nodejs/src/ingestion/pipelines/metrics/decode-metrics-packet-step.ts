import { Message } from 'node-rdkafka'

import { dlq, drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { metricMessageDlqCounter, metricMessageDroppedCounter } from './metrics'
import {
    DecodedMetricsPacket,
    MetricsPacketDecodeLimits,
    MetricsPacketTooLargeError,
    decodeMetricsPacket,
} from './metrics-avro'

export function createDecodeMetricsPacketStep<T extends { message: Message; teamId: number }>(
    limits: MetricsPacketDecodeLimits
): ProcessingStep<T, T & DecodedMetricsPacket> {
    return async function decodeMetricsPacketStep(input) {
        const value = input.message.value
        if (value === null) {
            metricMessageDroppedCounter.inc({ reason: 'null_value', team_id: input.teamId.toString() })
            return drop('null_value')
        }
        try {
            return ok({ ...input, ...(await decodeMetricsPacket(value, limits)) })
        } catch (error) {
            if (error instanceof MetricsPacketTooLargeError) {
                metricMessageDlqCounter.inc({ reason: 'packet_too_large', team_id: input.teamId.toString() })
                return dlq('metrics_packet_too_large', error)
            }
            metricMessageDlqCounter.inc({ reason: 'decode_failed', team_id: input.teamId.toString() })
            return dlq('metrics_decode_failed', error)
        }
    }
}
