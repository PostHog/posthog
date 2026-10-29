import { replayLayoutFrom } from './replayLayout'

describe('replayLayoutFrom', () => {
    it.each([
        [undefined, false, null, 'classic'],
        ['control', false, null, 'classic'],
        ['test', false, null, 'classic'],
        ['compact', false, null, 'compact'],
        ['youtube', false, null, 'youtube'],
        ['landing', true, null, 'classic'],
        ['control', false, 'landing', 'landing'],
        ['compact', true, 'classic', 'classic'],
    ])('flag %p, preferClassic %p, staff override %p gives %s', (flagValue, preferClassic, override, expected) => {
        expect(replayLayoutFrom(flagValue, preferClassic, override as any)).toBe(expected)
    })
})
