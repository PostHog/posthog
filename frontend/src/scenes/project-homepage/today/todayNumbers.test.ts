import { todayNumber } from './todayNumbers'

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
})
