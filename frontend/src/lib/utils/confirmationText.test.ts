import { matchesConfirmationText } from 'lib/utils/confirmationText'

describe('matchesConfirmationText', () => {
    it.each([
        ['delete', 'delete', true],
        ['Delete', 'delete', true],
        [' delete ', 'delete', true],
        ['delet', 'delete', false],
        ['', 'delete', false],
    ])('matchesConfirmationText(%p, %p) === %p', (input, expected, result) => {
        expect(matchesConfirmationText(input, expected)).toBe(result)
    })
})
