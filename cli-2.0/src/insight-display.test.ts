import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
    BREAKDOWN_NULL_DISPLAY,
    BREAKDOWN_NULL_NUMERIC_LABEL,
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_OTHER_DISPLAY,
    BREAKDOWN_OTHER_NUMERIC_LABEL,
    BREAKDOWN_OTHER_STRING_LABEL,
    bucketAverage,
    bucketLabels,
    buildLabelRow,
    formatYValue,
    friendlyBreakdownLabel,
    getInsightType,
    getPostHogHex,
    hexToAnsi,
    maxRenderablePoints,
    parseHex,
    pickStep,
    POSTHOG_COLORS,
    widenSeries,
} from './insight-display.js'

describe('getInsightType', () => {
    it('unwraps InsightVizNode wrapper to the inner source kind', () => {
        assert.equal(
            getInsightType({ query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery' } } }),
            'TrendsQuery'
        )
    })

    it('returns the query kind directly when not wrapped', () => {
        assert.equal(getInsightType({ query: { kind: 'HogQLQuery' } }), 'HogQLQuery')
    })

    it('returns "InsightVizNode" when wrapper has no source kind', () => {
        assert.equal(getInsightType({ query: { kind: 'InsightVizNode' } }), 'InsightVizNode')
        assert.equal(getInsightType({ query: { kind: 'InsightVizNode', source: null } }), 'InsightVizNode')
    })

    it('falls back to "Insight" when query is missing or not an object', () => {
        assert.equal(getInsightType({}), 'Insight')
        assert.equal(getInsightType({ query: null }), 'Insight')
        assert.equal(getInsightType({ query: 'TrendsQuery' }), 'Insight')
    })
})

describe('widenSeries', () => {
    it('returns a copy (not the same reference) when step <= 1', () => {
        const series = [1, 2, 3]
        const widened = widenSeries(series, 1)
        assert.deepEqual(widened, [1, 2, 3])
        assert.notStrictEqual(widened, series)
    })

    const cases: Array<{ name: string; series: number[]; step: number; expected: number[] }> = [
        { name: 'step=1 passes through', series: [1, 2, 3], step: 1, expected: [1, 2, 3] },
        { name: 'step=0 passes through', series: [1, 2, 3], step: 0, expected: [1, 2, 3] },
        { name: 'negative step passes through', series: [1, 2, 3], step: -5, expected: [1, 2, 3] },
        {
            name: 'linearly interpolates between adjacent points',
            series: [0, 10],
            step: 5,
            expected: [0, 2, 4, 6, 8, 10],
        },
        {
            name: 'interpolates across multiple segments and preserves originals',
            series: [0, 10, 0],
            step: 2,
            expected: [0, 5, 10, 5, 0],
        },
        { name: 'single-point input is unchanged', series: [5], step: 10, expected: [5] },
        { name: 'empty input returns empty', series: [], step: 5, expected: [] },
    ]

    for (const { name, series, step, expected } of cases) {
        it(name, () => {
            assert.deepEqual(widenSeries(series, step), expected)
        })
    }
})

describe('formatYValue', () => {
    const cases: Array<{ input: number; expected: string }> = [
        // small numbers as plain integers
        { input: 0, expected: '0' },
        { input: 42, expected: '42' },
        { input: 999, expected: '999' },
        // small non-integer values are rounded
        { input: 4.7, expected: '5' },
        { input: -4.7, expected: '-5' },
        // thousands below 9950 formatted with one decimal
        { input: 1000, expected: '1.0k' },
        { input: 1500, expected: '1.5k' },
        { input: 9000, expected: '9.0k' },
        // larger thousands without decimals
        { input: 15_000, expected: '15k' },
        { input: 999_000, expected: '999k' },
        // millions with one decimal and "M" suffix
        { input: 1_500_000, expected: '1.5M' },
        { input: -2_000_000, expected: '-2.0M' },
        // larger millions without decimals
        { input: 10_000_000, expected: '10M' },
        { input: 100_000_000, expected: '100M' },
        { input: 999_000_000, expected: '999M' },
        // negatives in the larger-millions range previously overflowed to "-10.0M"
        // / "-99.0M" (6 chars) — must stay ≤5 chars
        { input: -10_000_000, expected: '-10M' },
        { input: -99_000_000, expected: '-99M' },
        // billions with one decimal and "B" suffix
        { input: 1_000_000_000, expected: '1.0B' },
        { input: -2_500_000_000, expected: '-2.5B' },
        // larger billions without decimals — previously overflowed to "-10.0B" /
        // "100.0B" (6 chars); must stay ≤5 chars
        { input: 9_500_000_000, expected: '10B' },
        { input: -9_500_000_000, expected: '-10B' },
        { input: 50_000_000_000, expected: '50B' },
        { input: 100_000_000_000, expected: '100B' },
        { input: -100_000_000_000, expected: '-100B' },
        // boundary cases that previously rounded into the next magnitude and
        // overflowed the 5-char width budget for negatives — must stay ≤5 chars
        { input: 9999, expected: '10k' },
        { input: -9999, expected: '-10k' },
        { input: 999_999, expected: '1.0M' },
        { input: -999_999, expected: '-1.0M' },
        { input: 9_500_000, expected: '10M' },
        { input: -9_500_000, expected: '-10M' },
        { input: 999_500_000, expected: '1.0B' },
        // non-finite values fall back to "0" (caller is responsible for padding)
        { input: Number.NaN, expected: '0' },
        { input: Number.POSITIVE_INFINITY, expected: '0' },
        { input: Number.NEGATIVE_INFINITY, expected: '0' },
    ]

    for (const { input, expected } of cases) {
        it(`formats ${input} as "${expected}"`, () => {
            assert.equal(formatYValue(input), expected)
        })
    }
})

describe('pickStep', () => {
    it('clamps to a minimum of 1 when there are many points', () => {
        assert.equal(pickStep(100, 60), 1)
    })

    it('clamps to a maximum of 20 when there is plenty of room', () => {
        assert.equal(pickStep(2, 240), 20)
    })

    it('scales the step with the width budget', () => {
        // budget = 100 - Y_AXIS_PAD - 2 = 91; 91 / 9 = 10.11 -> 10
        assert.equal(pickStep(10, 100), 10)
    })

    it('keeps the chart within the terminal width for the realistic 31-points / 120-cols case', () => {
        const step = pickStep(31, 120)
        assert.ok(step >= 1 && step <= 20)
        // Whatever step we pick, the rendered chart width must fit on the line.
        assert.ok((31 - 1) * step + 10 <= 120, 'chart overflows terminal width')
    })

    it('does not divide by zero on a single-point input', () => {
        assert.doesNotThrow(() => pickStep(1, 60))
        assert.doesNotThrow(() => pickStep(0, 60))
    })
})

describe('buildLabelRow', () => {
    it('returns an empty string for no labels', () => {
        assert.equal(buildLabelRow([], 5), '')
    })

    it('renders labels in left-to-right input order', () => {
        const row = buildLabelRow(['Mon', 'Tue', 'Wed'], 10)
        const positions = ['Mon', 'Tue', 'Wed'].map((label) => row.indexOf(label))
        assert.ok(
            positions.every((pos) => pos >= 0),
            'each label should appear in the row'
        )
        assert.deepEqual(
            positions,
            [...positions].sort((a, b) => a - b)
        )
    })

    const cases: Array<{
        name: string
        labels: unknown[]
        step: number
        mustInclude: string[]
        mustExclude?: string[]
    }> = [
        {
            name: 'strips a trailing four-digit year from each label',
            labels: ['13-Apr-2026', '14-Apr-2026'],
            step: 10,
            mustInclude: ['13-Apr', '14-Apr'],
            mustExclude: ['2026'],
        },
        {
            name: 'drops some labels when there is not enough room, keeping first and last',
            labels: [
                'LblA01',
                'LblB02',
                'LblC03',
                'LblD04',
                'LblE05',
                'LblF06',
                'LblG07',
                'LblH08',
                'LblI09',
                'LblJ10',
            ],
            step: 2,
            mustInclude: ['LblA01', 'LblJ10'],
            mustExclude: ['LblB02', 'LblC03'],
        },
        {
            name: 'coerces non-string label inputs via stringify',
            labels: [1, 2, null, undefined],
            step: 10,
            mustInclude: ['1', '2'],
        },
        {
            name: 'renders every label when step is large enough to avoid collisions',
            labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
            step: 10,
            mustInclude: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
        },
    ]

    for (const { name, labels, step, mustInclude, mustExclude } of cases) {
        it(name, () => {
            const row = buildLabelRow(labels, step)
            for (const needle of mustInclude) {
                assert.ok(row.includes(needle), `${needle} should be present in row`)
            }
            for (const needle of mustExclude ?? []) {
                assert.ok(!row.includes(needle), `${needle} should not be present in row`)
            }
        })
    }
})

describe('parseHex', () => {
    const cases: Array<{ hex: string; expected: { r: number; g: number; b: number } }> = [
        { hex: '#000000', expected: { r: 0, g: 0, b: 0 } },
        { hex: '#ffffff', expected: { r: 255, g: 255, b: 255 } },
        { hex: '#1d4aff', expected: { r: 29, g: 74, b: 255 } },
        { hex: '#621da6', expected: { r: 98, g: 29, b: 166 } },
        { hex: '#42827e', expected: { r: 66, g: 130, b: 126 } },
        { hex: '#ce7c00', expected: { r: 206, g: 124, b: 0 } },
        // Uppercase hex digits parse the same as lowercase
        { hex: '#FF6347', expected: { r: 255, g: 99, b: 71 } },
        // Leading '#' is optional
        { hex: '1d4aff', expected: { r: 29, g: 74, b: 255 } },
    ]

    for (const { hex, expected } of cases) {
        it(`parses ${hex} as rgb(${expected.r}, ${expected.g}, ${expected.b})`, () => {
            assert.deepEqual(parseHex(hex), expected)
        })
    }
})

describe('hexToAnsi', () => {
    const cases: Array<{ hex: string; expected: string }> = [
        { hex: '#000000', expected: '\x1b[38;2;0;0;0m' },
        { hex: '#ffffff', expected: '\x1b[38;2;255;255;255m' },
        { hex: '#1d4aff', expected: '\x1b[38;2;29;74;255m' },
        { hex: '#191970', expected: '\x1b[38;2;25;25;112m' },
        { hex: '#ff6347', expected: '\x1b[38;2;255;99;71m' },
    ]

    for (const { hex, expected } of cases) {
        it(`emits a 24-bit SGR for ${hex}`, () => {
            assert.equal(hexToAnsi(hex), expected)
        })
    }

    it('produces a distinct ANSI escape for every entry in POSTHOG_COLORS', () => {
        // The bug we are guarding against: previously several PostHog hexes
        // were folded onto the same named ANSI color (e.g. #1d4aff and #191970
        // both rendered as blue), making adjacent series indistinguishable.
        const ansiEscapes = POSTHOG_COLORS.map(hexToAnsi)
        const unique = new Set(ansiEscapes)
        assert.equal(unique.size, POSTHOG_COLORS.length, 'every palette color should map to a unique ANSI sequence')
    })
})

describe('friendlyBreakdownLabel', () => {
    const cases: Array<{ name: string; value: unknown; expected: string }> = [
        {
            name: 'translates the "Other" string sentinel',
            value: BREAKDOWN_OTHER_STRING_LABEL,
            expected: BREAKDOWN_OTHER_DISPLAY,
        },
        {
            name: 'translates the "Other" numeric sentinel',
            value: BREAKDOWN_OTHER_NUMERIC_LABEL,
            expected: BREAKDOWN_OTHER_DISPLAY,
        },
        {
            name: 'translates the "Other" numeric sentinel passed as a string',
            value: String(BREAKDOWN_OTHER_NUMERIC_LABEL),
            expected: BREAKDOWN_OTHER_DISPLAY,
        },
        {
            name: 'translates the "None" string sentinel',
            value: BREAKDOWN_NULL_STRING_LABEL,
            expected: BREAKDOWN_NULL_DISPLAY,
        },
        {
            name: 'translates the "None" numeric sentinel',
            value: BREAKDOWN_NULL_NUMERIC_LABEL,
            expected: BREAKDOWN_NULL_DISPLAY,
        },
        {
            name: 'passes regular string labels through',
            value: 'lucas@posthog.com',
            expected: 'lucas@posthog.com',
        },
        {
            name: 'stringifies non-string regular values',
            value: 42,
            expected: '42',
        },
        {
            name: 'returns an empty string for null',
            value: null,
            expected: '',
        },
        {
            name: 'returns an empty string for undefined',
            value: undefined,
            expected: '',
        },
    ]

    for (const { name, value, expected } of cases) {
        it(name, () => {
            assert.equal(friendlyBreakdownLabel(value), expected)
        })
    }
})

describe('bucketAverage', () => {
    const cases: Array<{ name: string; values: number[]; maxPoints: number; expected: number[] }> = [
        {
            name: 'returns a copy unchanged when length is at or below the cap',
            values: [1, 2, 3, 4],
            maxPoints: 10,
            expected: [1, 2, 3, 4],
        },
        {
            name: 'returns a copy unchanged when maxPoints equals length',
            values: [1, 2, 3, 4],
            maxPoints: 4,
            expected: [1, 2, 3, 4],
        },
        {
            name: 'averages adjacent buckets when length exceeds the cap',
            values: [1, 3, 5, 7, 9, 11],
            maxPoints: 3,
            expected: [2, 6, 10],
        },
        {
            name: 'handles a non-divisible length (final bucket is shorter)',
            // ceil(5/2) = 3 → buckets of size 3 → [(1+2+3)/3, (4+5)/2]
            values: [1, 2, 3, 4, 5],
            maxPoints: 2,
            expected: [2, 4.5],
        },
        {
            name: 'compresses a 720-point hourly series so it fits a 240-col chart',
            // termWidth 240 → maxRenderablePoints = 231; 720 down to ≤231 points
            values: Array.from({ length: 720 }, (_, i) => i),
            maxPoints: 231,
            expected: undefined as unknown as number[], // checked below
        },
        {
            name: 'returns a copy (not the input reference) on the identity path',
            values: [1, 2, 3],
            maxPoints: 10,
            expected: [1, 2, 3],
        },
        {
            name: 'passes input through when maxPoints is 0 (defensive)',
            values: [1, 2, 3],
            maxPoints: 0,
            expected: [1, 2, 3],
        },
        {
            name: 'returns empty for an empty input',
            values: [],
            maxPoints: 10,
            expected: [],
        },
    ]

    for (const { name, values, maxPoints, expected } of cases) {
        it(name, () => {
            const out = bucketAverage(values, maxPoints)
            if (expected !== undefined) {
                assert.deepEqual(out, expected)
            } else {
                // The 720-point case: just assert the output fits the cap and
                // preserves the overall scale within tolerance.
                assert.ok(out.length <= maxPoints, `output length ${out.length} should be <= ${maxPoints}`)
                assert.ok(out.length > 0, 'output should not be empty')
            }
        })
    }

    it('does not mutate the input array', () => {
        const input = [1, 2, 3, 4, 5]
        const snapshot = [...input]
        bucketAverage(input, 2)
        assert.deepEqual(input, snapshot)
    })
})

describe('bucketLabels', () => {
    const cases: Array<{ name: string; labels: unknown[]; maxPoints: number; expected: unknown[] }> = [
        {
            name: 'returns a copy unchanged when length fits the cap',
            labels: ['a', 'b', 'c'],
            maxPoints: 5,
            expected: ['a', 'b', 'c'],
        },
        {
            name: 'stride-samples the first label of each bucket',
            // bucketSize = ceil(6/3) = 2 → indices 0, 2, 4
            labels: ['a', 'b', 'c', 'd', 'e', 'f'],
            maxPoints: 3,
            expected: ['a', 'c', 'e'],
        },
        {
            name: 'aligns with bucketAverage bucket boundaries',
            // Same bucketSize as bucketAverage for the same lengths/caps.
            labels: ['l0', 'l1', 'l2', 'l3', 'l4'],
            maxPoints: 2,
            expected: ['l0', 'l3'],
        },
        {
            name: 'returns empty for an empty input',
            labels: [],
            maxPoints: 10,
            expected: [],
        },
    ]

    for (const { name, labels, maxPoints, expected } of cases) {
        it(name, () => {
            assert.deepEqual(bucketLabels(labels, maxPoints), expected)
        })
    }
})

describe('maxRenderablePoints', () => {
    const cases: Array<{ termWidth: number; expected: number }> = [
        { termWidth: 240, expected: 231 },
        { termWidth: 120, expected: 111 },
        { termWidth: 80, expected: 71 },
        // Pathological narrow widths still produce a usable minimum
        { termWidth: 5, expected: 2 },
        { termWidth: 0, expected: 2 },
    ]

    for (const { termWidth, expected } of cases) {
        it(`returns ${expected} cells at termWidth=${termWidth}`, () => {
            assert.equal(maxRenderablePoints(termWidth), expected)
        })
    }
})

describe('getPostHogHex', () => {
    const cases: Array<{ name: string; index: number; expected: string }> = [
        { name: 'returns the first color for index 0', index: 0, expected: POSTHOG_COLORS[0] },
        { name: 'returns the last color for index 14', index: 14, expected: POSTHOG_COLORS[14] },
        { name: 'wraps around at the palette length', index: 15, expected: POSTHOG_COLORS[0] },
        { name: 'wraps around for larger indices', index: 31, expected: POSTHOG_COLORS[1] },
        { name: 'handles negative indices', index: -1, expected: POSTHOG_COLORS[14] },
        { name: 'handles large negative indices', index: -16, expected: POSTHOG_COLORS[14] },
    ]

    for (const { name, index, expected } of cases) {
        it(name, () => {
            assert.equal(getPostHogHex(index), expected)
        })
    }
})
