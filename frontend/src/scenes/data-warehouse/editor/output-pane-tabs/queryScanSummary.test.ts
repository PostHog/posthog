import {
    PredicateIndexUsage,
    PredicateIndexVerdict,
    PredicateScope,
    ScanEstimate,
    ScanEstimatePrecision,
    ScanEstimateSource,
    ScanEstimateTimeRange,
    TableScanEstimate,
} from '~/queries/schema/schema-general'

import { LARGE_SCAN_ROWS, describeTableScan, summarizeQueryScan, summarizeScan } from './queryScanSummary'

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

const eventsTable = (overrides: Partial<TableScanEstimate> = {}): TableScanEstimate => ({
    name: 'events',
    source: ScanEstimateSource.Events,
    precision: ScanEstimatePrecision.Measured,
    rows: 42_000_000,
    days: 30,
    events: [],
    time_range: ScanEstimateTimeRange.Bounded,
    ...overrides,
})

const unknownTable = (name: string): TableScanEstimate => ({
    name,
    source: ScanEstimateSource.Clickhouse,
    precision: ScanEstimatePrecision.Unknown,
})

const estimate = (overrides: Partial<ScanEstimate> = {}): ScanEstimate => ({
    rows: 42_000_000,
    upper_bound: false,
    tables: [eventsTable()],
    ...overrides,
})

describe('queryScanSummary', () => {
    it.each([
        ['bounded multi-day range', estimate(), 'Reads about 42M events (30 days)'],
        [
            'sub-two-day range reads as hours',
            estimate({ tables: [eventsTable({ days: 1.5 })] }),
            'Reads about 42M events (36 hours)',
        ],
        [
            'unmodelled indexed filter reads as a ceiling',
            estimate({ upper_bound: true }),
            'Reads up to 42M events (30 days)',
        ],
        [
            'open range says a year was assumed',
            estimate({ tables: [eventsTable({ time_range: ScanEstimateTimeRange.Open, days: 365 })] }),
            'Reads about 42M events (no date range, assuming a year)',
        ],
        [
            'several estimated tables count rows, not events',
            estimate({ tables: [eventsTable({ rows: 40_000_000 }), eventsTable({ rows: 2_000_000 })] }),
            'Reads about 42M rows · 2 tables',
        ],
        [
            'a table with no estimate is called out',
            estimate({ tables: [eventsTable(), unknownTable('persons')] }),
            'Reads about 42M rows · 1 of 2 tables estimated',
        ],
    ])('%s', (_name, input, expected) => {
        expect(summarizeScan(input)?.text).toBe(expected)
    })

    it('says nothing when no table has a number', () => {
        expect(summarizeScan(estimate({ rows: 0, tables: [unknownTable('persons')] }))).toBeNull()
    })

    it('warns at the large-scan threshold and not below it', () => {
        expect(summarizeScan(estimate({ rows: LARGE_SCAN_ROWS - 1 }))?.warn).toBe(false)
        expect(summarizeScan(estimate({ rows: LARGE_SCAN_ROWS }))?.warn).toBe(true)
    })

    it.each([
        [
            'an events scan names its range and events',
            eventsTable({ events: ['$pageview'] }),
            '42M rows (30 days, $pageview)',
        ],
        [
            'a size-only table says the read is not estimated',
            {
                name: 'orders',
                source: ScanEstimateSource.Warehouse,
                precision: ScanEstimatePrecision.SizeOnly,
                bytes: 356_515_840,
            },
            '340.00 MB on disk, read not estimated',
        ],
        ['an unknown table says so', unknownTable('persons'), 'no statistics yet'],
    ])('%s', (_name, table, expected) => {
        expect(describeTableScan(table)).toBe(expected)
    })

    it('joins the scan and filter sentences and warns if either does', () => {
        const summary = summarizeQueryScan([predicate(PredicateIndexVerdict.UnindexedJson)], estimate())

        expect(summary).toEqual({
            text: 'Reads about 42M events (30 days) · 1 filter reads every row',
            warn: true,
        })
    })

    it('renders nothing when there is neither an estimate nor a filter', () => {
        expect(summarizeQueryScan([], null)).toBeNull()
    })
})
