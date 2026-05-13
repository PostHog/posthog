import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { buildLabelRow, formatYValue, getInsightType, pickStep, widenSeries } from './insight-display.js'

describe('getInsightType', () => {
  it('unwraps InsightVizNode wrapper to the inner source kind', () => {
    assert.equal(
      getInsightType({ query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery' } } }),
      'TrendsQuery',
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
    { name: 'linearly interpolates between adjacent points', series: [0, 10], step: 5, expected: [0, 2, 4, 6, 8, 10] },
    { name: 'interpolates across multiple segments and preserves originals', series: [0, 10, 0], step: 2, expected: [0, 5, 10, 5, 0] },
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

  it('clamps to a maximum of 12 when there is plenty of room', () => {
    assert.equal(pickStep(2, 200), 12)
  })

  it('scales the step with the width budget', () => {
    // budget = 100 - Y_AXIS_PAD - 2 = 91; 91 / 9 = 10.11 -> 10
    assert.equal(pickStep(10, 100), 10)
  })

  it('keeps the chart within the terminal width for the realistic 31-points / 120-cols case', () => {
    const step = pickStep(31, 120)
    assert.ok(step >= 1 && step <= 12)
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
      'each label should appear in the row',
    )
    assert.deepEqual(positions, [...positions].sort((a, b) => a - b))
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
      labels: ['LblA01', 'LblB02', 'LblC03', 'LblD04', 'LblE05', 'LblF06', 'LblG07', 'LblH08', 'LblI09', 'LblJ10'],
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
