import {
    EventsScanEstimate,
    PredicateIndexUsage,
    PredicateIndexVerdict,
    PredicateScope,
} from '~/queries/schema/schema-general'

import { LARGE_SCAN_ROWS, summarizeQueryScan, summarizeScan } from './queryScanSummary'

const predicate = (verdict: PredicateIndexVerdict): PredicateIndexUsage => ({
    property_name: 'p',
    scope: PredicateScope.Event,
    operator: '==',
    source_label: 'JSON blob',
    semantic_type: 'String',
    physical_type: 'String',
    usable_indexes: [],
    verdict,
    message: '',
})

const estimate = (overrides: Partial<EventsScanEstimate> = {}): EventsScanEstimate => ({
    rows: 42_000_000,
    days: 30,
    events: [],
    time_range: 'bounded',
    ...overrides,
})

describe('queryScanSummary', () => {
    it.each([
        ['bounded multi-day range', estimate(), 'Reads up to 42M events (30 days)'],
        ['sub-two-day range reads as hours', estimate({ days: 1.5 }), 'Reads up to 42M events (36 hours)'],
        [
            'open range says a year was assumed',
            estimate({ time_range: 'open', days: 365 }),
            'Reads up to 42M events (no date range, assuming a year)',
        ],
    ])('%s', (_name, input, expected) => {
        expect(summarizeScan(input).text).toBe(expected)
    })

    it('warns at the large-scan threshold and not below it', () => {
        expect(summarizeScan(estimate({ rows: LARGE_SCAN_ROWS - 1 })).warn).toBe(false)
        expect(summarizeScan(estimate({ rows: LARGE_SCAN_ROWS })).warn).toBe(true)
    })

    it('joins the scan and filter sentences and warns if either does', () => {
        const summary = summarizeQueryScan([predicate(PredicateIndexVerdict.UnindexedJson)], estimate())

        expect(summary).toEqual({
            text: 'Reads up to 42M events (30 days) · 1 filter reads every row',
            warn: true,
        })
    })

    it('renders nothing when there is neither an estimate nor a filter', () => {
        expect(summarizeQueryScan([], null)).toBeNull()
    })
})
