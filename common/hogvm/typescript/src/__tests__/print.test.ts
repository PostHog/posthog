import { escapeIdentifier } from '../stl/print'

describe('hogvm print', () => {
    test('escapeIdentifier doubles embedded backticks', () => {
        expect(escapeIdentifier('safe` , 2 AS injected --')).toBe('`safe`` , 2 AS injected --`')
        expect(escapeIdentifier('safe\\`tick')).toBe('`safe\\\\``tick`')
    })
})
