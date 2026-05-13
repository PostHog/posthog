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
    // boundary cases that previously rounded into the next magnitude and
    // overflowed the 5-char width budget for negatives — must stay ≤5 chars
    { input: 9999, expected: '10k' },
    { input: -9999, expected: '-10k' },
    { input: 999_999, expected: '1.0M' },
    { input: -999_999, expected: '-1.0M' },
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

  it('strips a trailing four-digit year from each label', () => {
    const row = buildLabelRow(['13-Apr-2026', '14-Apr-2026'], 10)
    assert.ok(row.includes('13-Apr'))
    assert.ok(row.includes('14-Apr'))
    assert.ok(!row.includes('2026'))
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

  it('drops some labels when there is not enough room, keeping first and last', () => {
    const labels = ['LblA01', 'LblB02', 'LblC03', 'LblD04', 'LblE05', 'LblF06', 'LblG07', 'LblH08', 'LblI09', 'LblJ10']
    const row = buildLabelRow(labels, 2)
    const visible = labels.filter((l) => row.includes(l))
    assert.ok(visible.length < labels.length, 'cramped step should drop at least one label')
    assert.ok(visible.includes('LblA01'), 'first label is always rendered')
    assert.ok(visible.includes('LblJ10'), 'last label is always rendered')
  })

  it('coerces non-string label inputs via stringify', () => {
    const row = buildLabelRow([1, 2, null, undefined], 10)
    assert.ok(row.includes('1'))
    assert.ok(row.includes('2'))
  })

  it('renders every label when step is large enough to avoid collisions', () => {
    const row = buildLabelRow(['Mon', 'Tue', 'Wed', 'Thu', 'Fri'], 10)
    for (const day of ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']) {
      assert.ok(row.includes(day), `${day} should be rendered with step=10`)
    }
  })
})
