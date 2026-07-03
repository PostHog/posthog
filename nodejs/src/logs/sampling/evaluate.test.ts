import type { LogRecord } from '~/logs/log-record-avro'

import { compileRuleSet } from './compile-rules'
import {
    SAMPLING_DECISION_DROP,
    SAMPLING_DECISION_SAMPLE_DROPPED,
    SAMPLING_DECISION_SAMPLE_KEPT,
    classifySamplingRecord,
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

    it('path_drop with match_attribute_key matches only that attribute', () => {
        const rules = compileRuleSet([
            {
                id: 'p',
                rule_type: 'path_drop',
                scope_service: null,
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { patterns: ['^beta$'], match_attribute_key: 'ph.probe.suite' },
            },
        ])
        const rec = baseRecord()
        rec.attributes = { 'http.route': '/beta', 'ph.probe.suite': 'gamma' }
        expect(evaluateLogRecord(rules, rec).decision).not.toBe(SAMPLING_DECISION_DROP)
        const rec2 = baseRecord()
        rec2.attributes = { 'http.route': '/other', 'ph.probe.suite': 'beta' }
        expect(evaluateLogRecord(rules, rec2).decision).toBe(SAMPLING_DECISION_DROP)
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

    it('compileRuleSet converts kb_per_second to bytes using decimal KB', () => {
        const rs = compileRuleSet([
            {
                id: 'rl-kb',
                rule_type: 'rate_limit',
                scope_service: null,
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { kb_per_second: 1, burst_kb: 2 },
            },
        ])
        // The drop-rule UI (UNIT_TO_KB_PER_S), the preview threshold line (KB/s × 1000),
        // and the API validator ("1000000 = 1 GB/s") all treat KB as decimal — the
        // bucket must enforce the same unit or every cap runs above its label.
        expect(rs.rules[0]?.rateLimit).toEqual({ refillPerSecond: 1000, poolMax: 2000, costUnit: 'bytes' })
    })

    it('path_drop with non-array patterns config matches nothing', () => {
        const rules = compileRuleSet([
            {
                id: 'p-bad',
                rule_type: 'path_drop',
                scope_service: null,
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { patterns: 'abc' },
            },
        ])
        // A corrupt non-array value must not be iterated per character into
        // single-char regexes, each of which would match nearly every path.
        const rec = baseRecord()
        rec.attributes = { 'http.route': '/api/cart' }
        expect(evaluateLogRecord(rules, rec).decision).not.toBe(SAMPLING_DECISION_DROP)
    })

    it('compileRuleSet marks hasRateLimitRules for valid rate_limit config', () => {
        const rs = compileRuleSet([
            {
                id: 'rl',
                rule_type: 'rate_limit',
                scope_service: 'api',
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { logs_per_second: 100, burst_logs: 300 },
            },
        ])
        expect(rs.hasRateLimitRules).toBe(true)
        expect(rs.rules[0]?.rateLimit).toEqual({ refillPerSecond: 100, poolMax: 300, costUnit: 'records' })
    })

    it('classifySamplingRecord defers to rate_limit when first matching rule', () => {
        const rules = compileRuleSet([
            {
                id: 'rl',
                rule_type: 'rate_limit',
                scope_service: 'api',
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { logs_per_second: 10 },
            },
        ])
        const rec = baseRecord()
        rec.service_name = 'api'
        expect(classifySamplingRecord(rules, rec)).toEqual({ kind: 'rate_limit', ruleId: 'rl' })
    })

    it('classifySamplingRecord skips rate_limit when service scope does not match', () => {
        const rules = compileRuleSet([
            {
                id: 'rl',
                rule_type: 'rate_limit',
                scope_service: 'other',
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { logs_per_second: 10 },
            },
        ])
        const rec = baseRecord()
        rec.service_name = 'api'
        expect(classifySamplingRecord(rules, rec).kind).toBe('resolved')
    })

    describe('rate_limit with config.filter_group', () => {
        // Same outer envelope shape the drop-rules UI emits, matching the path_drop tests below.
        const wrap = (inner: object): object => ({ type: 'AND', values: [inner] })

        it('classifySamplingRecord returns rate_limit when filter_group matches', () => {
            const rules = compileRuleSet([
                {
                    id: 'rl-fg',
                    rule_type: 'rate_limit',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: {
                        logs_per_second: 10,
                        filter_group: wrap({
                            type: 'AND',
                            values: [{ key: 'service.name', operator: 'exact', value: 'api' }],
                        }),
                    },
                },
            ])
            const rec = baseRecord()
            rec.service_name = 'api'
            expect(classifySamplingRecord(rules, rec)).toEqual({ kind: 'rate_limit', ruleId: 'rl-fg' })
        })

        it('classifySamplingRecord skips rate_limit when filter_group does not match', () => {
            const rules = compileRuleSet([
                {
                    id: 'rl-fg',
                    rule_type: 'rate_limit',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: {
                        logs_per_second: 10,
                        filter_group: wrap({
                            type: 'AND',
                            values: [{ key: 'service.name', operator: 'exact', value: 'api' }],
                        }),
                    },
                },
            ])
            const rec = baseRecord()
            rec.service_name = 'other'
            // Rule has no other scoping, so without filter_group honor, this would return rate_limit
            // and rate-limit every log on the team. With the fix, it falls through to keep.
            expect(classifySamplingRecord(rules, rec).kind).toBe('resolved')
        })

        it('classifySamplingRecord still requires scope_service AND filter_group when both set', () => {
            const rules = compileRuleSet([
                {
                    id: 'rl-both',
                    rule_type: 'rate_limit',
                    scope_service: 'api',
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: {
                        logs_per_second: 10,
                        filter_group: wrap({
                            type: 'AND',
                            values: [{ key: 'severity_text', operator: 'exact', value: 'error' }],
                        }),
                    },
                },
            ])
            const apiInfo = baseRecord()
            apiInfo.service_name = 'api'
            apiInfo.severity_text = 'info'
            // scope_service matches but filter_group doesn't → skip.
            expect(classifySamplingRecord(rules, apiInfo).kind).toBe('resolved')

            const apiError = baseRecord()
            apiError.service_name = 'api'
            apiError.severity_text = 'error'
            // Both match → rate_limit.
            expect(classifySamplingRecord(rules, apiError)).toEqual({ kind: 'rate_limit', ruleId: 'rl-both' })
        })
    })

    it('path_drop match runs before rate_limit in rule order', () => {
        const rules = compileRuleSet([
            {
                id: 'pd',
                rule_type: 'path_drop',
                scope_service: null,
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { patterns: ['/healthz'] },
            },
            {
                id: 'rl',
                rule_type: 'rate_limit',
                scope_service: 'api',
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { logs_per_second: 10 },
            },
        ])
        const rec = baseRecord()
        expect(classifySamplingRecord(rules, rec)).toEqual({
            kind: 'resolved',
            decision: SAMPLING_DECISION_DROP,
            ruleId: 'pd',
        })
    })

    describe('path_drop with config.filter_group', () => {
        // The drop-rules UI writes the inner group wrapped in an outer AND envelope:
        //   { type: 'AND', values: [ { type: 'AND'|'OR', values: [<leaves>] } ] }
        const wrap = (inner: object): object => ({ type: 'AND', values: [inner] })

        it('drops when filter_group matches alone (no patterns)', () => {
            const rules = compileRuleSet([
                {
                    id: 'fg',
                    rule_type: 'path_drop',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: {
                        patterns: [],
                        filter_group: wrap({
                            type: 'AND',
                            values: [{ key: 'service.name', operator: 'exact', value: 'api' }],
                        }),
                    },
                },
            ])
            const matching = baseRecord()
            matching.service_name = 'api'
            expect(evaluateLogRecord(rules, matching).decision).toBe(SAMPLING_DECISION_DROP)

            const nonMatching = baseRecord()
            nonMatching.service_name = 'other'
            expect(evaluateLogRecord(rules, nonMatching).decision).not.toBe(SAMPLING_DECISION_DROP)
        })

        it('drops when EITHER patterns OR filter_group matches (transition OR semantics)', () => {
            const rules = compileRuleSet([
                {
                    id: 'both',
                    rule_type: 'path_drop',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: {
                        patterns: ['/healthz'],
                        filter_group: wrap({
                            type: 'AND',
                            values: [{ key: 'severity_text', operator: 'exact', value: 'fatal' }],
                        }),
                    },
                },
            ])
            // Match via legacy patterns only
            const patternsOnly = baseRecord()
            patternsOnly.attributes = { 'http.route': '/healthz' }
            expect(evaluateLogRecord(rules, patternsOnly).decision).toBe(SAMPLING_DECISION_DROP)

            // Match via filter_group only
            const filterOnly = baseRecord()
            filterOnly.attributes = { 'http.route': '/api' }
            filterOnly.severity_text = 'fatal'
            expect(evaluateLogRecord(rules, filterOnly).decision).toBe(SAMPLING_DECISION_DROP)

            // Match neither
            const neither = baseRecord()
            neither.attributes = { 'http.route': '/api' }
            neither.severity_text = 'info'
            expect(evaluateLogRecord(rules, neither).decision).not.toBe(SAMPLING_DECISION_DROP)
        })

        it('empty filter_group does not drop (conservative)', () => {
            const rules = compileRuleSet([
                {
                    id: 'empty',
                    rule_type: 'path_drop',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: {
                        patterns: [],
                        filter_group: wrap({ type: 'AND', values: [] }),
                    },
                },
            ])
            expect(evaluateLogRecord(rules, baseRecord()).decision).not.toBe(SAMPLING_DECISION_DROP)
        })

        it('filter_group with too many sibling nodes is dropped at compile time (legacy row above breadth cap)', () => {
            // Pre-validator rows could have grown beyond the breadth cap. Walking
            // them per record would amount to O(leaves) per log line, so
            // parseFilterGroup discards the group entirely — the rule becomes a
            // patterns-only rule. Matches MAX_FILTER_GROUP_NODES in compile-rules.ts.
            const tooMany = Array.from({ length: 300 }, (_, i) => ({
                key: 'service.name',
                operator: 'exact',
                value: `svc-${i}`,
            }))
            const rules = compileRuleSet([
                {
                    id: 'oversize',
                    rule_type: 'path_drop',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: {
                        patterns: [],
                        filter_group: wrap({ type: 'AND', values: tooMany }),
                    },
                },
            ])
            const rec = baseRecord()
            rec.service_name = 'svc-1'
            // Group was discarded → no patterns → rule never drops.
            expect(evaluateLogRecord(rules, rec).decision).not.toBe(SAMPLING_DECISION_DROP)
        })

        it('classifySamplingRecord drops via filter_group match', () => {
            const rules = compileRuleSet([
                {
                    id: 'fg',
                    rule_type: 'path_drop',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: {
                        patterns: [],
                        filter_group: wrap({
                            type: 'AND',
                            values: [{ key: 'severity_text', operator: 'in', value: ['error', 'fatal'] }],
                        }),
                    },
                },
            ])
            const rec = baseRecord()
            rec.severity_text = 'error'
            expect(classifySamplingRecord(rules, rec)).toEqual({
                kind: 'resolved',
                decision: SAMPLING_DECISION_DROP,
                ruleId: 'fg',
            })
        })
    })

    describe('deterministic drops outrank rate_limit regardless of priority', () => {
        // A rate-limit bucket is a finite shared resource; if a record was going to be
        // dropped anyway by a deterministic rule, charging the bucket for it just
        // starves legitimate traffic for no reason. So path_drop / severity_sampling
        // ALWAYS resolve a record before rate_limit can claim it, even when rate_limit
        // appears first in the priority-ordered rule list.

        it.each([
            {
                label: 'path_drop wins when rate_limit appears earlier in rule order',
                extraRule: {
                    id: 'pd-second',
                    rule_type: 'path_drop' as const,
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: { patterns: ['/healthz'] },
                },
                patchRecord: (_rec: LogRecord) => {},
                expected: { kind: 'resolved', decision: SAMPLING_DECISION_DROP, ruleId: 'pd-second' },
            },
            {
                label: 'severity_sampling drop wins when rate_limit appears earlier in rule order',
                extraRule: {
                    id: 'ss-second',
                    rule_type: 'severity_sampling' as const,
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: {
                        actions: {
                            DEBUG: { type: 'keep' },
                            INFO: { type: 'drop' },
                            WARN: { type: 'keep' },
                            ERROR: { type: 'keep' },
                        },
                    },
                },
                patchRecord: (rec: LogRecord) => {
                    rec.severity_text = 'info'
                },
                expected: { kind: 'resolved', decision: SAMPLING_DECISION_DROP, ruleId: 'ss-second' },
            },
        ])('$label', ({ extraRule, patchRecord, expected }) => {
            const rules = compileRuleSet([
                {
                    id: 'rl-first',
                    rule_type: 'rate_limit',
                    scope_service: 'api',
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: { logs_per_second: 10 },
                },
                extraRule,
            ])
            const rec = baseRecord()
            rec.service_name = 'api'
            patchRecord(rec)
            expect(classifySamplingRecord(rules, rec)).toEqual(expected)
        })

        it('severity_sampling drop wins when rate_limit appears earlier in rule order', () => {
            const rules = compileRuleSet([
                {
                    id: 'rl-first',
                    rule_type: 'rate_limit',
                    scope_service: 'api',
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: { logs_per_second: 10 },
                },
                {
                    id: 'ss-second',
                    rule_type: 'severity_sampling',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: {
                        actions: {
                            DEBUG: { type: 'keep' },
                            INFO: { type: 'drop' },
                            WARN: { type: 'keep' },
                            ERROR: { type: 'keep' },
                        },
                    },
                },
            ])
            const rec = baseRecord()
            rec.service_name = 'api'
            rec.severity_text = 'info'
            expect(classifySamplingRecord(rules, rec)).toEqual({
                kind: 'resolved',
                decision: SAMPLING_DECISION_DROP,
                ruleId: 'ss-second',
            })
        })

        it('severity_sampling keep wins over later rate_limit (record is preserved, bucket not charged)', () => {
            const rules = compileRuleSet([
                {
                    id: 'rl-first',
                    rule_type: 'rate_limit',
                    scope_service: 'api',
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: { logs_per_second: 10 },
                },
                {
                    id: 'ss-second',
                    rule_type: 'severity_sampling',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: {
                        actions: {
                            DEBUG: { type: 'keep' },
                            INFO: { type: 'keep' },
                            WARN: { type: 'keep' },
                            ERROR: { type: 'keep' },
                        },
                    },
                },
            ])
            const rec = baseRecord()
            rec.service_name = 'api'
            expect(classifySamplingRecord(rules, rec)).toEqual({
                kind: 'resolved',
                decision: 'keep',
                ruleId: 'ss-second',
            })
        })

        it('rate_limit still wins when no deterministic rule resolves the record', () => {
            const rules = compileRuleSet([
                {
                    id: 'rl-first',
                    rule_type: 'rate_limit',
                    scope_service: 'api',
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: { logs_per_second: 10 },
                },
                {
                    id: 'pd-noop',
                    rule_type: 'path_drop',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: { patterns: ['/never-matches'] },
                },
            ])
            const rec = baseRecord()
            rec.service_name = 'api'
            expect(classifySamplingRecord(rules, rec)).toEqual({ kind: 'rate_limit', ruleId: 'rl-first' })
        })

        it('first matching rate_limit rule wins when multiple rate_limit rules apply and no deterministic rule resolves', () => {
            const rules = compileRuleSet([
                {
                    id: 'rl-a',
                    rule_type: 'rate_limit',
                    scope_service: 'api',
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: { logs_per_second: 10 },
                },
                {
                    id: 'rl-b',
                    rule_type: 'rate_limit',
                    scope_service: 'api',
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: { logs_per_second: 100 },
                },
            ])
            const rec = baseRecord()
            rec.service_name = 'api'
            expect(classifySamplingRecord(rules, rec)).toEqual({ kind: 'rate_limit', ruleId: 'rl-a' })
        })

        it('alwaysKeep on a later rule still pre-empts an earlier rate_limit match', () => {
            // alwaysKeep already short-circuits to KEEP today; this guards against a
            // future refactor accidentally letting rate_limit win over an explicit
            // alwaysKeep that sits after it in the priority order.
            const rules = compileRuleSet([
                {
                    id: 'rl-first',
                    rule_type: 'rate_limit',
                    scope_service: 'api',
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: { logs_per_second: 10 },
                },
                {
                    id: 'keep-errors',
                    rule_type: 'severity_sampling',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: {
                        actions: {
                            DEBUG: { type: 'drop' },
                            INFO: { type: 'drop' },
                            WARN: { type: 'keep' },
                            ERROR: { type: 'keep' },
                        },
                        always_keep: { status_gte: 500 },
                    },
                },
            ])
            const rec = baseRecord()
            rec.service_name = 'api'
            rec.attributes = { 'http.status_code': '503' }
            expect(classifySamplingRecord(rules, rec)).toEqual({
                kind: 'resolved',
                decision: 'keep',
                ruleId: 'keep-errors',
            })
        })
    })
})
