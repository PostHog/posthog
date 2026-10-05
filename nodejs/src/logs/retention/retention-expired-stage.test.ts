import type { LogRecord } from '~/logs/log-record-avro'
import { runPipelineStages } from '~/logs/pipeline/log-processing-pipeline'

import { canHoldExpiredRow, makeRetentionExpiredStage } from './retention-expired-stage'

const MICROS_PER_DAY = 86_400_000_000
const NOW_MICROS = 1_790_000_000_000_000
const daysAgo = (days: number): number => NOW_MICROS - days * MICROS_PER_DAY

describe('retention expired stage', () => {
    const record = (uuid: string, timestamp: number, retentionDays?: number): LogRecord => ({
        uuid,
        trace_id: null,
        span_id: null,
        trace_flags: null,
        timestamp,
        observed_timestamp: NOW_MICROS,
        body: 'x',
        severity_text: 'info',
        severity_number: 9,
        service_name: 'api',
        resource_attributes: null,
        instrumentation_scope: null,
        event_name: null,
        attributes: null,
        retention_days: retentionDays,
    })

    it.each([
        { label: 'older than the team default', timestamp: daysAgo(31), retentionDays: undefined, kept: false },
        { label: 'one day inside the team default', timestamp: daysAgo(29), retentionDays: undefined, kept: true },
        {
            label: 'inside the default but past a shorter stamped rule',
            timestamp: daysAgo(20),
            retentionDays: 14,
            kept: false,
        },
        {
            label: 'stamped with 0 days, which falls back to the team default like ClickHouse does',
            timestamp: daysAgo(20),
            retentionDays: 0,
            kept: true,
        },
        {
            label: 'past the default but inside a longer stamped rule',
            timestamp: daysAgo(60),
            retentionDays: 90,
            kept: true,
        },
    ])('a row $label is kept: $kept', async ({ timestamp, retentionDays, kept }) => {
        const result = await runPipelineStages(
            [record('row', timestamp, retentionDays)],
            [makeRetentionExpiredStage(1, 30, NOW_MICROS)]
        )
        expect(result.kept.length === 1).toBe(kept)
        expect(result.stats.droppedBy).toBe(kept ? undefined : 'retention_expired')
        expect(result.stats.contentBytesTotal).toBe(1)
    })

    it.each([
        { label: 'has no header', minTimestamp: undefined, shortest: 14, expected: false },
        {
            label: 'holds only rows inside the shortest retention',
            minTimestamp: daysAgo(13),
            shortest: 14,
            expected: false,
        },
        { label: 'holds a row past the shortest retention', minTimestamp: daysAgo(15), shortest: 14, expected: true },
    ])('a message that $label is checked: $expected', ({ minTimestamp, shortest, expected }) => {
        expect(canHoldExpiredRow(minTimestamp, shortest, NOW_MICROS)).toBe(expected)
    })
})
