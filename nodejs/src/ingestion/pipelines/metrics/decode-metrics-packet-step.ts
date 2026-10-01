import { Message } from 'node-rdkafka'

import { dlq, drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { metricMessageDlqCounter, metricMessageDroppedCounter } from './metrics'
import { DecodedMetricsPacket, decodeMetricsPacket } from './metrics-avro'
import { MetricRecord } from './types'

export function createDecodeMetricsPacketStep<T extends { message: Message; teamId: number }>(): ProcessingStep<
    T,
    T & DecodedMetricsPacket
> {
    return async function decodeMetricsPacketStep(input) {
        const value = input.message.value
        if (value === null) {
            metricMessageDroppedCounter.inc({ reason: 'null_value', team_id: input.teamId.toString() })
            return drop('null_value')
        }
        try {
            return ok({ ...input, ...(await decodeMetricsPacket(value)) })
        } catch (error) {
            metricMessageDlqCounter.inc({ reason: 'decode_failed', team_id: input.teamId.toString() })
            return dlq('metrics_decode_failed', error)
        }
    }
}

export interface MetricRecordSubElement {
    record: MetricRecord
}

/** Fan-out: one sub-element per decoded row. Sub-steps only see the row. */
export function fanOutMetricRecords(element: { records: MetricRecord[] }): MetricRecordSubElement[] {
    return element.records.map((record) => ({ record }))
}

/** Fan-in: the rows that survived the sub-pipeline replace the packet's rows. */
export function fanInMetricRecords<T extends { records: MetricRecord[] }>(
    element: T,
    subResults: MetricRecordSubElement[]
): T {
    return { ...element, records: subResults.map((sub) => sub.record) }
}
