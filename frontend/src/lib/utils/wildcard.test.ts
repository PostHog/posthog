import { createWildcardMatcher } from './wildcard'

describe('createWildcardMatcher', () => {
    it.each(['*', '%'] as const)('agrees with the anchored regex grammar for %p on seeded short inputs', (wildcard) => {
        let seed = 71011
        const alphabet = ['a', 'b', '*', '%', '.', '[', '\\', '\n', '\r', '\u2028', '\u2029', '\ud83d', '\ude00']
        const random = (): number => (seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0)
        const word = (): string => {
            const length = random() % 9
            return Array.from({ length }, () => alphabet[random() % alphabet.length]).join('')
        }
        for (let index = 0; index < 600; index++) {
            const value = word()
            const pattern = index % 3 === 0 ? `${wildcard}${value.slice(0, 3)}${wildcard}` : word()
            const regex = new RegExp(
                `^${pattern
                    .split(wildcard)
                    .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
                    .join('.*')}$`
            )
            expect(createWildcardMatcher(pattern, wildcard)(value)).toBe(regex.test(value))
        }
    })

    it.each([
        ['', '', true],
        ['', '\n', false],
        ['*', '', true],
        ['*', '\n', false],
        ['a*', 'a\n', false],
        ['a*', 'a\r', false],
        ['a*', 'a\u2028', false],
        ['a*', 'a\u2029', false],
        ['a\n*', 'a\nb', true],
        ['**a***b**', 'ab', true],
        ['*\ud83d*', '\ud83d\ude00', true],
        ['*a'.repeat(24) + 'b', 'a'.repeat(2000), false],
    ])('matches %p against %p', (pattern, value, expected) => {
        expect(createWildcardMatcher(pattern)(value)).toBe(expected)
    })
})
