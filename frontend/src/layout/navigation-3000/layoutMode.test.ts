import { resolveLayoutMode } from './layoutMode'

describe('resolveLayoutMode', () => {
    it.each([
        ['none', false, false, 'bare'],
        ['minimal', false, false, 'minimal'],
        ['embedded', false, false, 'embedded'],
        ['full', false, false, 'classic'],
        ['full', false, true, 'classic'],
        ['full', true, false, 'today-framed'],
        ['full', true, true, 'today-phone'],
    ] as const)('maps mode %s with todayRail %s and phoneLayout %s to %s', (mode, todayRail, phoneLayout, expected) => {
        expect(resolveLayoutMode({ mode, todayRail, phoneLayout })).toBe(expected)
    })
})
