import type { LogRecord } from '~/logs/log-record-avro'

import { MAX_ENABLED_RETENTION_RULES, compileRetentionRuleSet } from './compile-retention-rules'
import { evaluateRetentionDays, safeEvaluateRetentionDays } from './evaluate-retention'

describe('logs retention rules', () => {
    const record = (overrides: Partial<LogRecord> = {}): LogRecord => ({
        uuid: null,
        trace_id: null,
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
        attributes: null,
        ...overrides,
    })

    const serviceRule = (id: string, service: string, retentionDays: number) => ({
        id,
        config: {
            retention_days: retentionDays,
            filter_group: {
                type: 'AND',
                values: [
                    {
                        type: 'AND',
                        values: [
                            { key: 'service.name', type: 'log_resource_attribute', operator: 'exact', value: service },
                        ],
                    },
                ],
            },
        },
    })

    it('returns the first matching rule in priority order', () => {
        // Rows arrive pre-ordered by priority; a later rule also matching must not win.
        const ruleSet = compileRetentionRuleSet([serviceRule('a', 'api', 90), serviceRule('b', 'api', 30)])
        expect(evaluateRetentionDays(ruleSet, record({ service_name: 'api' }))).toBe(90)
    })

    it('returns null when no rule matches so the caller applies the team default', () => {
        const ruleSet = compileRetentionRuleSet([serviceRule('a', 'billing', 90)])
        expect(evaluateRetentionDays(ruleSet, record({ service_name: 'api' }))).toBeNull()
    })

    it('drops rows whose retention_days is not an allowed tier', () => {
        const ruleSet = compileRetentionRuleSet([serviceRule('a', 'api', 45), serviceRule('b', 'api', 30)])
        expect(ruleSet.rules).toHaveLength(1)
        expect(evaluateRetentionDays(ruleSet, record({ service_name: 'api' }))).toBe(30)
    })

    it('ignores a rule with a missing filter_group (matches nothing)', () => {
        const ruleSet = compileRetentionRuleSet([{ id: 'a', config: { retention_days: 30 } }])
        expect(evaluateRetentionDays(ruleSet, record({ service_name: 'api' }))).toBeNull()
    })

    it('caps compiled rules at MAX_ENABLED_RETENTION_RULES to bound per-record work', () => {
        const rows = Array.from({ length: MAX_ENABLED_RETENTION_RULES + 50 }, (_, i) =>
            serviceRule(`r${i}`, `svc${i}`, 30)
        )
        expect(compileRetentionRuleSet(rows).rules).toHaveLength(MAX_ENABLED_RETENTION_RULES)
    })

    it('fails open to null when evaluation throws', () => {
        const poisoned = { rules: [{ id: 'a', retentionDays: 30, filterGroup: {} as any }] }
        const spy = jest.spyOn(require('../sampling/filter-group-match'), 'matchFilterGroup').mockImplementation(() => {
            throw new Error('boom')
        })
        expect(safeEvaluateRetentionDays(poisoned as any, record(), 1)).toBeNull()
        spy.mockRestore()
    })
})
