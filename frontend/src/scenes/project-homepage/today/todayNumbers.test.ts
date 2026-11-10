import { todayChangeText, todayNumber } from './todayNumbers'

describe('todayNumber', () => {
    test.each([
        [342, '342'],
        [1240, '1.2k'],
        [967_000, '967k'],
        [999_960, '1M'],
        [999.96, '1k'],
        [1_000, '1k'],
        [2_350_000, '2.4M'],
        [-6200, '-6.2k'],
        [4.25, '4.3'],
    ])('formats %s as %s', (value, expected) => {
        expect(todayNumber(value)).toBe(expected)
    })

    test.each([
        [18.4, '%', 0, '+18%'],
        [-3.2, '%', 0, '−3%'],
        [0.2, '%', 0, '0%'],
        [1234, '%', 0, '+1,234%'],
        [0.42, '%', 2, '+0.42%'],
        [-0.4, '%', 2, '−0.4%'],
        [8.24, '%', 1, '+8.2%'],
        [2.36, 'pp', 0, '+2.4 pp'],
        [-0.04, 'pp', 0, '0 pp'],
    ] as const)('writes the change %s %s with %s decimals as %s', (change, unit, decimals, expected) => {
        expect(todayChangeText(change, unit, decimals)).toBe(expected)
    })
})
