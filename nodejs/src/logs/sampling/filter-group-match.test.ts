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

    describe('wire-encoded attribute values', () => {
        // Capture JSON-encodes attribute values onto the Avro wire, so a string
        // attribute reaches this matcher as `"production"` — quotes included. The
        // ClickHouse sink and the transformation path both decode before they
        // compare. The matcher must see the same decoded values: without decoding,
        // an enabled rule silently never fires, and a negated operator fires on
        // exactly the lines it was meant to keep.
        const wireRecord = () =>
            baseRecord({
                resource_attributes: { 'deployment.environment': '"production"' },
                attributes: { 'http.status_code': '500', ratio: '"12.5"' },
            })

        it.each<[string, string | string[], boolean]>([
            ['exact', ['production'], true],
            ['in', ['staging', 'production'], true],
            // Negation must not fire on the value it names — that would drop
            // the lines the rule was written to keep.
            ['is_not', ['production'], false],
            ['starts_with', 'prod', true],
            ['ends_with', 'tion', true],
            ['regex', '^production$', true],
            ['icontains', 'production', true],
        ])('%s %j sees the decoded resource attribute → %s', (operator, value, expected) => {
            const g = group({
                values: [{ key: 'deployment.environment', type: 'log_resource_attribute', operator, value }],
            })
            expect(matchFilterGroup(g, wireRecord())).toBe(expected)
        })

        it('numeric comparison parses a JSON-encoded numeric string', () => {
            const g = group({ values: [{ key: 'ratio', type: 'log_attribute', operator: 'gt', value: 10 }] })
            expect(matchFilterGroup(g, wireRecord())).toBe(true)
        })
        it('unquoted JSON numbers pass through unchanged', () => {
            const g = group({
                values: [{ key: 'http.status_code', type: 'log_attribute', operator: 'exact', value: '500' }],
            })
            expect(matchFilterGroup(g, wireRecord())).toBe(true)
        })
        it('severity fallback through the attribute map is decoded', () => {
            const g = group({ values: [{ key: 'severity_text', operator: 'exact', value: ['error'] }] })
            expect(matchFilterGroup(g, baseRecord({ attributes: { level: '"error"' } }))).toBe(true)
        })
        it('service.name fallback through the resource map is decoded', () => {
            const g = group({ values: [{ key: 'service.name', operator: 'exact', value: 'api' }] })
            expect(matchFilterGroup(g, baseRecord({ resource_attributes: { 'service.name': '"api"' } }))).toBe(true)
        })
        it('a quoted-but-invalid-JSON value is compared as-is', () => {
            const g = group({
                values: [{ key: 'raw', type: 'log_attribute', operator: 'exact', value: '"a"b"' }],
            })
            expect(matchFilterGroup(g, baseRecord({ attributes: { raw: '"a"b"' } }))).toBe(true)
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
