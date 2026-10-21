import { replayLayoutFrom } from './replayLayout'

describe('replayLayoutFrom', () => {
    it.each([
        [undefined, false, 'classic'],
        [false, false, 'classic'],
        ['control', false, 'classic'],
        ['test', false, 'watch'],
        ['test', true, 'classic'],
    ])('flag %p with preferClassicLayout %p gives %s', (flagValue, preferClassicLayout, expected) => {
        expect(replayLayoutFrom(flagValue, preferClassicLayout)).toBe(expected)
    })
})
