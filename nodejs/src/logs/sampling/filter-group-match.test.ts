import type { LogRecord } from '~/logs/log-record-avro'

import { type FilterGroupNode, MAX_FILTER_GROUP_DEPTH, matchFilterGroup } from './filter-group-match'

const baseRecord = (overrides: Partial<LogRecord> = {}): LogRecord => ({
    uuid: null,
    trace_id: null,
    span_id: null,
    trace_flags: null,
    timestamp: null,
    observed_timestamp: null,
    body: null,
    severity_text: null,
    severity_number: null,
    service_name: null,
    resource_attributes: null,
    instrumentation_scope: null,
    event_name: null,
    attributes: null,
    ...overrides,
})

const group = (overrides: Partial<FilterGroupNode>): FilterGroupNode => ({
    type: 'AND',
    values: [],
    ...overrides,
})

describe('matchFilterGroup', () => {
    describe('empty groups', () => {
        it('AND with no values returns false (conservative — do not drop)', () => {
            expect(matchFilterGroup(group({ type: 'AND', values: [] }), baseRecord())).toBe(false)
        })
        it('OR with no values returns false', () => {
            expect(matchFilterGroup(group({ type: 'OR', values: [] }), baseRecord())).toBe(false)
        })
    })

    describe('AND / OR semantics', () => {
        it('AND requires every leaf to match', () => {
            const g = group({
                type: 'AND',
                values: [
                    { key: 'service.name', operator: 'exact', value: 'api' },
                    { key: 'severity_text', operator: 'exact', value: 'error' },
                ],
            })
            expect(matchFilterGroup(g, baseRecord({ service_name: 'api', severity_text: 'error' }))).toBe(true)
            expect(matchFilterGroup(g, baseRecord({ service_name: 'api', severity_text: 'warn' }))).toBe(false)
        })
        it('OR matches when any leaf matches', () => {
            const g = group({
                type: 'OR',
                values: [
                    { key: 'severity_text', operator: 'exact', value: 'error' },
                    { key: 'severity_text', operator: 'exact', value: 'fatal' },
                ],
            })
            expect(matchFilterGroup(g, baseRecord({ severity_text: 'error' }))).toBe(true)
            expect(matchFilterGroup(g, baseRecord({ severity_text: 'fatal' }))).toBe(true)
            expect(matchFilterGroup(g, baseRecord({ severity_text: 'warn' }))).toBe(false)
        })
    })

    describe('nested groups', () => {
        it('AND-of-ORs evaluates correctly', () => {
            const g: FilterGroupNode = {
                type: 'AND',
                values: [
                    { key: 'service.name', operator: 'exact', value: 'api' },
                    {
                        type: 'OR',
                        values: [
                            { key: 'severity_text', operator: 'exact', value: 'error' },
                            { key: 'severity_text', operator: 'exact', value: 'fatal' },
                        ],
                    },
                ],
            }
            expect(matchFilterGroup(g, baseRecord({ service_name: 'api', severity_text: 'error' }))).toBe(true)
            expect(matchFilterGroup(g, baseRecord({ service_name: 'api', severity_text: 'warn' }))).toBe(false)
            expect(matchFilterGroup(g, baseRecord({ service_name: 'other', severity_text: 'error' }))).toBe(false)
        })
    })

    describe('record value lookup', () => {
        it('service.name resolves to LogRecord.service_name (first-class column)', () => {
            const g = group({ values: [{ key: 'service.name', operator: 'exact', value: 'api' }] })
            expect(matchFilterGroup(g, baseRecord({ service_name: 'api' }))).toBe(true)
            expect(matchFilterGroup(g, baseRecord({ resource_attributes: { 'service.name': 'api' } }))).toBe(true)
        })
        it('service_name (underscore) key still resolves via the OTel-canonical service.name attribute', () => {
            // Regression guard for the prior bug where the underscore-form filter
            // looked up `resource_attributes['service_name']`, which OTel never
            // populates — the value only lives under the dotted key.
            const g = group({ values: [{ key: 'service_name', operator: 'exact', value: 'api' }] })
            expect(matchFilterGroup(g, baseRecord({ service_name: 'api' }))).toBe(true)
            expect(matchFilterGroup(g, baseRecord({ resource_attributes: { 'service.name': 'api' } }))).toBe(true)
            expect(matchFilterGroup(g, baseRecord({ resource_attributes: { service_name: 'api' } }))).toBe(false)
        })
        it('severity_text resolves to LogRecord.severity_text (first-class column)', () => {
            const g = group({ values: [{ key: 'severity_text', operator: 'in', value: ['error', 'fatal'] }] })
            expect(matchFilterGroup(g, baseRecord({ severity_text: 'error' }))).toBe(true)
            expect(matchFilterGroup(g, baseRecord({ severity_text: 'info' }))).toBe(false)
        })
        it('severity_level is an alias for severity_text (the key the drop-rule UI writes)', () => {
            // Regression guard: the drop-rule builder persists severity filters as
            // `{key: 'severity_level', type: 'log'}`. Before the alias existed this
            // fell through to the `type: 'log'` body fallback and compared the log
            // BODY against e.g. "info" — so UI-created severity rules never matched.
            const g = group({
                values: [{ key: 'severity_level', type: 'log', operator: 'exact', value: ['info'] }],
            })
            expect(matchFilterGroup(g, baseRecord({ severity_text: 'info' }))).toBe(true)
            expect(matchFilterGroup(g, baseRecord({ severity_text: 'error' }))).toBe(false)
            // Must not match via the body fallback.
            expect(matchFilterGroup(g, baseRecord({ severity_text: 'error', body: 'info' }))).toBe(false)
        })
        it('level is an alias for severity_text (UI surfaces it this way)', () => {
            const g = group({
                values: [{ key: 'level', type: 'log_attribute', operator: 'exact', value: ['info', 'INFO'] }],
            })
            expect(matchFilterGroup(g, baseRecord({ severity_text: 'info' }))).toBe(true)
            expect(matchFilterGroup(g, baseRecord({ severity_text: 'error' }))).toBe(false)
        })
        it('level / severity_text resolve symmetrically when only an attribute is populated', () => {
            // When the first-class column is null, the attribute fallback must
            // produce the same value for both filter keys. The SDK convention
            // (Winston/Pino/etc.) stores severity under `level`; we fall back
            // to both attribute names regardless of which key the filter used.
            const recordWithLevelAttr = baseRecord({
                severity_text: null,
                attributes: { level: 'info' },
            })
            const levelFilter = group({ values: [{ key: 'level', operator: 'exact', value: 'info' }] })
            const severityFilter = group({ values: [{ key: 'severity_text', operator: 'exact', value: 'info' }] })
            expect(matchFilterGroup(levelFilter, recordWithLevelAttr)).toBe(true)
            expect(matchFilterGroup(severityFilter, recordWithLevelAttr)).toBe(true)

            // Same symmetry when the (rare) `severity_text` attribute is populated instead.
            const recordWithSeverityAttr = baseRecord({
                severity_text: null,
                attributes: { severity_text: 'info' },
            })
            expect(matchFilterGroup(levelFilter, recordWithSeverityAttr)).toBe(true)
            expect(matchFilterGroup(severityFilter, recordWithSeverityAttr)).toBe(true)
        })
        it('message resolves to LogRecord.body', () => {
            const g = group({ values: [{ key: 'message', type: 'log', operator: 'icontains', value: 'health' }] })
            expect(matchFilterGroup(g, baseRecord({ body: 'GET /healthz' }))).toBe(true)
            expect(matchFilterGroup(g, baseRecord({ body: 'GET /api/v1' }))).toBe(false)
        })
        it('log_resource_attribute reads from record.resource_attributes', () => {
            const g = group({
                values: [
                    {
                        key: 'deployment.environment',
                        type: 'log_resource_attribute',
                        operator: 'exact',
                        value: 'staging',
                    },
                ],
            })
            expect(
                matchFilterGroup(g, baseRecord({ resource_attributes: { 'deployment.environment': 'staging' } }))
            ).toBe(true)
            expect(matchFilterGroup(g, baseRecord({ attributes: { 'deployment.environment': 'staging' } }))).toBe(false)
        })
        it('log_attribute reads from record.attributes', () => {
            const g = group({
                values: [{ key: 'http.route', type: 'log_attribute', operator: 'exact', value: '/healthz' }],
            })
            expect(matchFilterGroup(g, baseRecord({ attributes: { 'http.route': '/healthz' } }))).toBe(true)
            expect(matchFilterGroup(g, baseRecord({ resource_attributes: { 'http.route': '/healthz' } }))).toBe(false)
        })
        it('untyped leaf falls back through attributes then resource_attributes', () => {
            const g = group({ values: [{ key: 'http.route', operator: 'exact', value: '/healthz' }] })
            expect(matchFilterGroup(g, baseRecord({ attributes: { 'http.route': '/healthz' } }))).toBe(true)
            expect(matchFilterGroup(g, baseRecord({ resource_attributes: { 'http.route': '/healthz' } }))).toBe(true)
        })
        it('missing attribute does not match comparison operators', () => {
            const g = group({ values: [{ key: 'http.route', operator: 'exact', value: '/healthz' }] })
            expect(matchFilterGroup(g, baseRecord())).toBe(false)
        })
    })

    describe('recursion depth cap', () => {
        // Build a degenerate AND-chain N levels deep wrapping a single matching leaf.
        function deepGroup(depth: number, leaf: { key: string; value: string; operator: string }): FilterGroupNode {
            let node: FilterGroupNode = { type: 'AND', values: [leaf] }
            for (let i = 0; i < depth; i++) {
                node = { type: 'AND', values: [node] }
            }
            return node
        }

        it('matches at exactly the depth cap boundary', () => {
            const g = deepGroup(MAX_FILTER_GROUP_DEPTH - 2, {
                key: 'service.name',
                value: 'api',
                operator: 'exact',
            })
            expect(matchFilterGroup(g, baseRecord({ service_name: 'api' }))).toBe(true)
        })

        it('returns false past the depth cap without throwing', () => {
            const g = deepGroup(MAX_FILTER_GROUP_DEPTH + 5, {
                key: 'service.name',
                value: 'api',
                operator: 'exact',
            })
            expect(matchFilterGroup(g, baseRecord({ service_name: 'api' }))).toBe(false)
        })
    })
})
