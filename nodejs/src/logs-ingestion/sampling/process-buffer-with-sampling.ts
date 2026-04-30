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
import { logsSamplingDebugLog } from './sampling-debug-log'

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
    const decisionCounts: Record<string, number> = {}
    const dropByRuleId = new Map<string, number>()
    const maxPerRecordDebugLines = 24
    let perRecordLines = 0

    for (const record of records) {
        const { decision, ruleId } = evaluateLogRecord(ruleSet, record)
        decisionCounts[decision] = (decisionCounts[decision] ?? 0) + 1
        if (decision === SAMPLING_DECISION_DROP || decision === SAMPLING_DECISION_SAMPLE_DROPPED) {
            recordsDropped++
            if (ruleId) {
                dropByRuleId.set(ruleId, (dropByRuleId.get(ruleId) ?? 0) + 1)
            }
            if (perRecordLines < maxPerRecordDebugLines) {
                logsSamplingDebugLog('record dropped/sampled out', {
                    decision,
                    ruleId,
                    service: record.service_name,
                    route:
                        record.attributes?.['http.route'] ??
                        record.attributes?.['url.path'] ??
                        record.attributes?.['path'],
                    severity: record.severity_text,
                })
                perRecordLines++
            }
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

    logsSamplingDebugLog('processBufferWithSampling done', {
        inputRecords: records.length,
        kept: kept.length,
        dropped: recordsDropped,
        decisionCounts,
        dropByRuleId: Object.fromEntries(dropByRuleId),
        settingsFlags: {
            json_parse_logs: settings.json_parse_logs ?? false,
            pii_scrub_logs: settings.pii_scrub_logs ?? false,
        },
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
