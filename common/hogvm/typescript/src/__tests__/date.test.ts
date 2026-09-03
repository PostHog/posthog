import { dateStringToSeconds, toDate, toDateTime, toUnixTimestamp } from '../stl/date'

/**
 * The shared date-like grammar. The canonical spec lives above `parse_datetime_to_seconds` in
 * `rust/common/hogvm/src/stl.rs`; the same table is driven by `rust/common/hogvm/tests/datetime.rs`
 * and `common/hogvm/python/test/test_date.py`. All three must agree — before this was pinned, only
 * 4 of these 34 inputs produced the same answer in all three VMs.
 */
const ACCEPTED: [string, number][] = [
    ['2024-01-01', 1704067200],
    ['2024-01-01T00:00:00Z', 1704067200],
    ['2024-01-01t00:00:00z', 1704067200], // RFC3339 says the designators are case-insensitive
    ['2024-01-01T00:00:00.000Z', 1704067200],
    ['2024-01-01T00:00:00', 1704067200], // naive => UTC, never the host zone
    ['2024-01-01 00:00:00', 1704067200], // the ClickHouse form HogQL emits; luxon alone rejected it
    ['2024-01-01T00:00', 1704067200],
    ['2024-01-01T00:00:00+05:00', 1704049200],
    ['2024-01-01 00:00:00+05:00', 1704049200],
    ['2024-01-01T00:00:00-0500', 1704085200], // offset without the colon
    ['2024-01-01T00:00:00.123Z', 1704067200.123],
    ['2024-01-01T00:00:00.123456Z', 1704067200.123], // truncated to ms, not rounded
    ['  2024-01-01  ', 1704067200],
    ['2024-01-01T00:00:00+05', 1704049200], // offset hours only
    ['2024-01-01T00:00:00,123Z', 1704067200.123], // comma fraction separator
    ['1960-01-01T00:00:00.123Z', -315619199.877], // pre-epoch: truncation must not flip sign
]

const REJECTED = [
    '2024', // luxon accepted these five as instants; a string property could plausibly hold any
    '2024-01',
    '20240101',
    '2024-W05',
    '2024-001',
    '12:30', // luxon resolved this against *today's* date
    '1700000000', // only Rust accepted this, and now only via its explicit native (see its tests)
    'not-a-date',
    '',
    '2024-13-01',
    '2024-02-30',
    '2024-01-01T24:00:00Z', // luxon normalized hour 24 to the next midnight; the others rejected
    '2024-01-01T00:00.123Z', // a fraction requires seconds; luxon rejected what the others took
    '2024-01-01T00:00:00+24:00', // made Python datetime.timezone RAISE out of the comparison path
    '2024-01-01T00:00:00+99:99', // same
    '0000-01-01', // valid to chrono and luxon, not to Python datetime
    '2024-01-01T25:00:00Z', // out-of-range hour
    '2024-01-01T00:60:00Z', // out-of-range minute
    '٢٠٢٤-٠١-٠١', // Unicode digits. JS's \d is ASCII-only so these never matched here, but \d matches
    // them in the Python/Rust engines: Python's int() read the first as a real date, and the other
    // two byte-sliced mid-codepoint in Rust — a panic. Pinned in all three tables.
    '2024-01-01T00:00+0١',
    '2024-01-01T00:00:00.١٢Z',
]

describe('date-like string grammar', () => {
    test.each(ACCEPTED)('accepts %s as %d', (input, expected) => {
        expect(dateStringToSeconds(input)).toBeCloseTo(expected, 3)
        expect(toDateTime(input).dt).toBeCloseTo(expected, 3)
        expect(toUnixTimestamp(input)).toBeCloseTo(expected, 3)
    })

    test.each(REJECTED)('rejects %p', (input) => {
        expect(dateStringToSeconds(input)).toBeNull()
    })

    test('a naive string resolves to UTC regardless of the host timezone', () => {
        // Python's `datetime.timestamp()` resolved naive input in the host zone, so the same filter
        // gave different answers on a developer's laptop and in production. Pinned in all three VMs.
        expect(toDateTime('2024-01-01').dt).toBe(1704067200)
        expect(toDate('2024-01-01')).toEqual({
            __hogDate__: true,
            year: 2024,
            month: 1,
            day: 1,
        })
    })

    test('an explicit zone applies only to input carrying no zone of its own', () => {
        expect(toDateTime('2024-01-01 00:00:00', 'America/New_York').dt).toBe(1704085200)
        expect(toDateTime('2024-01-01T00:00:00Z', 'America/New_York').dt).toBe(1704067200)
    })

    test('a number passes through as epoch seconds without parsing', () => {
        expect(toDateTime(1700000000).dt).toBe(1700000000)
    })

    test('unparseable input keeps the pre-existing NaN failure mode', () => {
        // Not a good failure mode, but each VM's is different (Python raises, Rust errors into a
        // null) and converging them is a separate change from converging what parses.
        expect(toDateTime('not-a-date').dt).toBeNaN()
    })

    test.each([[1700000000], [null], [{ a: 1 }], [['x']]])(
        'non-string input %p yields NaN rather than throwing',
        (input) => {
            // `toUnixTimestamp` guards only the two Hog temporal shapes and passes everything else
            // to the parser, and callers hand it raw event properties — so a non-string has to fall
            // through to the pre-existing NaN, not throw `input.trim is not a function` out of the VM.
            // (A number reaching `toDateTime` is separate: that has an explicit epoch-seconds branch.)
            expect(toUnixTimestamp(input as any)).toBeNaN()
        }
    )

    test.each([[null], [{ a: 1 }], [['x']]])('toDateTime(%p) yields NaN rather than throwing', (input) => {
        expect(toDateTime(input as any).dt).toBeNaN()
    })

    test('an ambiguous local time takes the first of the DST fold', () => {
        // 01:30 happens twice on 2024-11-03 in New York; Rust's `LocalResult::Ambiguous(dt, _)` and
        // luxon take the first (-04:00). Pinned because pytz's `localize` defaults to the second.
        expect(toUnixTimestamp('2024-11-03 01:30:00', 'America/New_York')).toBe(1730611800)
    })
})
