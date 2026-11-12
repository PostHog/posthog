import { replayLayoutFrom, staffReplayLayout } from './replayLayout'

describe('replayLayoutFrom', () => {
    it.each([
        [undefined, false, null, 'classic'],
        ['control', false, null, 'classic'],
        ['test', false, null, 'classic'],
        ['compact', false, null, 'compact'],
        ['youtube', false, null, 'youtube'],
        ['landing', false, null, 'landing'],
        ['landing', true, null, 'classic'],
        ['control', false, 'youtube', 'youtube'],
        ['compact', true, 'classic', 'classic'],
    ])('flag %p, preferClassic %p, staff override %p gives %s', (flagValue, preferClassic, override, expected) => {
        expect(replayLayoutFrom(flagValue, preferClassic, override as any)).toBe(expected)
    })
})

describe('staffReplayLayout', () => {
    it.each([
        [null, 'classic'],
        ['landing', 'classic'],
        ['classic', 'classic'],
        ['compact', 'compact'],
        ['youtube', 'youtube'],
    ])('stored override %p gives %s', (stored, expected) => {
        expect(staffReplayLayout(stored as any)).toBe(expected)
    })
})
