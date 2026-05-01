import { trace } from '@opentelemetry/api'

import { instrumented } from '~/common/tracing/tracing-utils'
import type { LogsSettings } from '~/types'

import { type PiiScrubStats } from '../log-pii-scrub'
import {
    type LogRecord,
    decodeLogRecords,
    encodeLogRecords,
    transformDecodedLogRecordsInPlace,
} from '../log-record-avro'
import type { CompiledRuleSet } from './evaluate'
import { SAMPLING_DECISION_DROP, SAMPLING_DECISION_SAMPLE_DROPPED, evaluateLogRecord } from './evaluate'

const samplingProcessInstrumentOpts = { measureTime: false, sendException: false } as const

export type ProcessBufferWithSamplingResult = {
    value: Buffer
    pii: PiiScrubStats
    recordsDropped: number
    /** When true, the caller must not produce this message to downstream Kafka (all lines sampled out). */
    allDropped: boolean
}

async function processBufferWithSamplingImpl(
    buffer: Buffer,
    settings: LogsSettings,
    ruleSet: CompiledRuleSet
): Promise<ProcessBufferWithSamplingResult> {
    const [logRecordType, compressionCodec, records] = await decodeLogRecords(buffer)
    if (!logRecordType) {
        throw new Error('avro schema metadata not found')
    }
    const pii = await transformDecodedLogRecordsInPlace(records, settings)
    const kept: LogRecord[] = []
    let recordsDropped = 0

    for (const record of records) {
        const { decision } = evaluateLogRecord(ruleSet, record)
        if (decision === SAMPLING_DECISION_DROP || decision === SAMPLING_DECISION_SAMPLE_DROPPED) {
            recordsDropped++
            continue
        }
        kept.push(record)
    }

    trace.getActiveSpan()?.setAttributes({
        'logs.sampling.input_record_count': records.length,
        'logs.sampling.kept_record_count': kept.length,
        'logs.sampling.dropped_record_count': recordsDropped,
        'logs.sampling.all_dropped': kept.length === 0,
        'logs.sampling.json_parse_logs': Boolean(settings.json_parse_logs),
        'logs.sampling.pii_scrub_logs': Boolean(settings.pii_scrub_logs),
    })

    if (kept.length === 0) {
        return { value: Buffer.alloc(0), pii, recordsDropped, allDropped: true }
    }
    const value = await encodeLogRecords(logRecordType, compressionCodec, kept)
    return { value, pii, recordsDropped, allDropped: false }
}

export const processBufferWithSampling = instrumented({
    key: 'logsIngestion.sampling.processBufferWithSampling',
    ...samplingProcessInstrumentOpts,
})(processBufferWithSamplingImpl)
