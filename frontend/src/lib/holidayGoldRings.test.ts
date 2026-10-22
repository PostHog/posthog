import { shouldPlayGoldRings } from './holidayGoldRings'

describe('shouldPlayGoldRings', () => {
    test.each([
        ['December 24', new Date(2026, 11, 24), true, '5 rings', false],
        ['December 25', new Date(2026, 11, 25), true, '5 rings', true],
        ['December 31', new Date(2026, 11, 31), true, '5 rings', true],
        ['January 1', new Date(2027, 0, 1), true, '5 rings', true],
        ['January 5', new Date(2027, 0, 5), true, '5 rings', true],
        ['January 6', new Date(2027, 0, 6), true, '5 rings', false],
        ['flag off', new Date(2026, 11, 25), false, '5 rings', false],
        ['no standalone 5', new Date(2026, 11, 25), true, '15 rings', false],
        ['no 5', new Date(2026, 11, 25), true, 'gold rings', false],
    ] as const)('%s', (_name, date, enabled, content, expected) => {
        expect(shouldPlayGoldRings(date, enabled, content)).toBe(expected)
    })
})
