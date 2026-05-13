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
  it('returns a copy when step <= 1', () => {
    const series = [1, 2, 3]
    const widened = widenSeries(series, 1)
    assert.deepEqual(widened, [1, 2, 3])
    assert.notStrictEqual(widened, series)

    assert.deepEqual(widenSeries([1, 2, 3], 0), [1, 2, 3])
    assert.deepEqual(widenSeries([1, 2, 3], -5), [1, 2, 3])
  })

  it('linearly interpolates between adjacent points', () => {
    assert.deepEqual(widenSeries([0, 10], 5), [0, 2, 4, 6, 8, 10])
  })

  it('interpolates across multiple segments and preserves originals', () => {
    assert.deepEqual(widenSeries([0, 10, 0], 2), [0, 5, 10, 5, 0])
  })

  it('handles single-point and empty inputs without throwing', () => {
    assert.deepEqual(widenSeries([5], 10), [5])
    assert.deepEqual(widenSeries([], 5), [])
  })
})

describe('formatYValue', () => {
  it('formats small numbers as plain integers', () => {
    assert.equal(formatYValue(0), '0')
    assert.equal(formatYValue(42), '42')
    assert.equal(formatYValue(999), '999')
  })

  it('rounds non-integer small values', () => {
    assert.equal(formatYValue(4.7), '5')
    assert.equal(formatYValue(-4.7), '-5')
  })

  it('formats thousands below 10k with one decimal', () => {
    assert.equal(formatYValue(1000), '1.0k')
    assert.equal(formatYValue(1500), '1.5k')
    assert.equal(formatYValue(9999), '10.0k')
  })

  it('formats larger thousands without decimals', () => {
    assert.equal(formatYValue(15_000), '15k')
    assert.equal(formatYValue(999_000), '999k')
  })

  it('formats millions with one decimal and "M" suffix', () => {
    assert.equal(formatYValue(1_500_000), '1.5M')
    assert.equal(formatYValue(-2_000_000), '-2.0M')
  })

  it('returns "0" for non-finite values (caller is responsible for padding)', () => {
    assert.equal(formatYValue(Number.NaN), '0')
    assert.equal(formatYValue(Number.POSITIVE_INFINITY), '0')
    assert.equal(formatYValue(Number.NEGATIVE_INFINITY), '0')
  })
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
