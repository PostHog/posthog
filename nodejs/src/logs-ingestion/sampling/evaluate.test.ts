import type { LogRecord } from '../log-record-avro'
import { compileRuleSet } from './compile-rules'
import {
    SAMPLING_DECISION_DROP,
    SAMPLING_DECISION_SAMPLE_DROPPED,
    SAMPLING_DECISION_SAMPLE_KEPT,
    evaluateLogRecord,
    severityOrdinalFromRecord,
} from './evaluate'

describe('evaluateLogRecord', () => {
    const baseRecord = (): LogRecord => ({
        uuid: null,
        trace_id: Buffer.from('abcd0123', 'hex'),
        span_id: null,
        trace_flags: null,
        timestamp: null,
        observed_timestamp: null,
        body: 'x',
        severity_text: 'info',
        severity_number: 9,
        service_name: 'api',
        resource_attributes: null,
        instrumentation_scope: null,
        event_name: null,
        attributes: { 'http.route': '/healthz' },
    })

    it('same trace_id yields deterministic sample decision', () => {
        const rules = compileRuleSet([
            {
                id: '1',
                rule_type: 'severity_sampling',
                scope_service: null,
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: {
                    actions: {
                        DEBUG: { type: 'drop' },
                        INFO: { type: 'sample', rate: 0.5 },
                        WARN: { type: 'keep' },
                        ERROR: { type: 'keep' },
                    },
                },
            },
        ])
        const r1 = baseRecord()
        const r2 = baseRecord()
        const a = evaluateLogRecord(rules, r1).decision
        const b = evaluateLogRecord(rules, r2).decision
        expect(a).toEqual(b)
    })

    it('path_drop matches pattern', () => {
        const rules = compileRuleSet([
            {
                id: 'p',
                rule_type: 'path_drop',
                scope_service: null,
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { patterns: ['/healthz'] },
            },
        ])
        const rec = baseRecord()
        expect(evaluateLogRecord(rules, rec).decision).toBe(SAMPLING_DECISION_DROP)
        const rec2 = baseRecord()
        rec2.attributes = { 'http.route': '/api' }
        expect(evaluateLogRecord(rules, rec2).decision).not.toBe(SAMPLING_DECISION_DROP)
    })

    it('severity ordinal maps info', () => {
        const r = baseRecord()
        expect(severityOrdinalFromRecord(r)).toBe(1)
    })

    it('sample rate ~50% over many distinct traces', () => {
        const rules = compileRuleSet([
            {
                id: 's',
                rule_type: 'severity_sampling',
                scope_service: null,
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: {
                    actions: {
                        DEBUG: { type: 'keep' },
                        INFO: { type: 'sample', rate: 0.5 },
                        WARN: { type: 'keep' },
                        ERROR: { type: 'keep' },
                    },
                },
            },
        ])
        let kept = 0
        const n = 20_000
        for (let i = 0; i < n; i++) {
            const rec = baseRecord()
            rec.trace_id = Buffer.alloc(16)
            rec.trace_id.writeUInt32BE(i, 0)
            const d = evaluateLogRecord(rules, rec).decision
            if (d === SAMPLING_DECISION_SAMPLE_KEPT || d === SAMPLING_DECISION_SAMPLE_DROPPED) {
                if (d === SAMPLING_DECISION_SAMPLE_KEPT) {
                    kept++
                }
            }
        }
        const ratio = kept / n
        expect(ratio).toBeGreaterThan(0.4)
        expect(ratio).toBeLessThan(0.6)
    })

    it('compiled rules evaluate within a loose throughput bound (regression guard)', () => {
        const rules = compileRuleSet([
            {
                id: 'perf',
                rule_type: 'severity_sampling',
                scope_service: null,
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: {
                    actions: {
                        DEBUG: { type: 'drop' },
                        INFO: { type: 'sample', rate: 0.25 },
                        WARN: { type: 'keep' },
                        ERROR: { type: 'keep' },
                    },
                },
            },
        ])
        const rec = baseRecord()
        const n = 40_000
        const t0 = Date.now()
        for (let i = 0; i < n; i++) {
            rec.trace_id = Buffer.alloc(16)
            rec.trace_id.writeUInt32BE(i, 0)
            evaluateLogRecord(rules, rec)
        }
        const elapsed = Date.now() - t0
        expect(elapsed).toBeLessThan(10_000)
    })
})
