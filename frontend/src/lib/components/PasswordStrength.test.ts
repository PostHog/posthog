import { validatePassword } from './PasswordStrength'

describe('validatePassword', () => {
    beforeAll(async () => {
        // zxcvbn loads asynchronously, so score the first password only once the module is in
        validatePassword('load zxcvbn')
        await import('zxcvbn')
        await new Promise((resolve) => setTimeout(resolve, 0))
    })

    test.each([
        ['', 0, undefined],
        ['x'.repeat(73), 0, 'Maximum 72 characters'],
        ['short', 2, 'Must be at least 8 characters long'],
        ['password', 1, 'This password is too easy to guess. Make it longer, or use a few unrelated words.'],
        ['test test test', 3, 'This password is still easy to guess. Add more words or characters.'],
        // The backend accepts a zxcvbn score of 3, so the form must not block this one
        ['wintergreen lamp', 4, undefined],
        ['correct horse battery staple', 5, undefined],
    ])('scores %p', (password, score, feedback) => {
        expect(validatePassword(password)).toEqual({ score, feedback })
    })
})
