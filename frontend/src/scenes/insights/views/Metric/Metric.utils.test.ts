import { computeMetricChange, MAX_CHANGE_PERCENT, MetricChangeResult } from './Metric.utils'

describe('computeMetricChange', () => {
    const cases: { name: string; data: number[] | undefined; expected: MetricChangeResult }[] = [
        { name: 'undefined data → no change', data: undefined, expected: { change: undefined, startValue: undefined } },
        { name: 'empty series → no change', data: [], expected: { change: undefined, startValue: undefined } },
        { name: 'single point → no change', data: [5], expected: { change: undefined, startValue: undefined } },
        { name: 'increase', data: [100, 150], expected: { change: { value: 50 }, startValue: 100 } },
        {
            name: 'decrease',
            data: [150, 100],
            expected: { change: { value: ((100 - 150) / 150) * 100 }, startValue: 150 },
        },
        {
            name: 'zero start, positive end → +∞',
            data: [0, 50],
            expected: { change: { value: 1, label: '∞' }, startValue: 0 },
        },
        { name: 'zero start, zero end → no movement', data: [0, 0], expected: { change: null, startValue: 0 } },
        {
            name: 'zero start, negative end → -∞',
            data: [0, -5],
            expected: { change: { value: -1, label: '∞' }, startValue: 0 },
        },
        {
            name: 'near-zero start over cap → ∞ (value preserved)',
            data: [0.001, 50],
            expected: { change: { value: ((50 - 0.001) / 0.001) * 100, label: '∞' }, startValue: 0.001 },
        },
        {
            name: 'exactly at cap → ∞',
            data: [1, 101],
            expected: { change: { value: MAX_CHANGE_PERCENT, label: '∞' }, startValue: 1 },
        },
        {
            name: 'non-finite values filtered out',
            data: [NaN, 100, 200],
            expected: { change: { value: 100 }, startValue: 100 },
        },
        { name: 'negative start increasing', data: [-100, -50], expected: { change: { value: 50 }, startValue: -100 } },
    ]

    it.each(cases)('$name', ({ data, expected }) => {
        expect(computeMetricChange(data)).toEqual(expected)
    })
})
