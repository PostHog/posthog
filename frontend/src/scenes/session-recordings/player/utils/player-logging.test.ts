import { categorizeWarning, isIgnoredWarning } from './player-logging'

describe('categorizeWarning', () => {
    it.each([
        {
            name: 'extracts first sentence from rrweb node-not-found warning',
            args: ['Could not find node with id 1234. This is expected if the DOM has changed.'],
            expected: 'Could not find node with id 1234',
        },
        {
            name: 'extracts first sentence from multi-sentence warning',
            args: ['Unknown tag: custom-element! This might cause rendering issues.'],
            expected: 'Unknown tag: custom-element',
        },
        {
            name: 'truncates long strings at 80 chars',
            args: ['A'.repeat(100) + '. Second sentence.'],
            expected: 'A'.repeat(80),
        },
        {
            name: 'handles Error objects',
            args: [new Error('Something went wrong in replay')],
            expected: 'Something went wrong in replay',
        },
        {
            name: 'returns unknown for non-string, non-Error args',
            args: [42],
            expected: 'unknown warning',
        },
        {
            name: 'returns unknown for empty args',
            args: [],
            expected: 'unknown warning',
        },
        {
            name: 'handles undefined first arg',
            args: [undefined],
            expected: 'unknown warning',
        },
        {
            name: 'handles newlines in warning',
            args: ['First line\nSecond line\nThird line'],
            expected: 'First line',
        },
        {
            name: 'handles string with no sentence-ending punctuation',
            args: ['Something happened with no punctuation'],
            expected: 'Something happened with no punctuation',
        },
        {
            name: 'handles string starting with exclamation',
            args: ['!important warning about replay'],
            expected: '!important warning about replay',
        },
        {
            name: 'skips prefix-like [replayer] and uses second arg',
            args: ['[replayer]', 'Could not find node with id 42. Skipping mutation.'],
            expected: 'Could not find node with id 42',
        },
        {
            name: 'skips prefix-like [replayer] and categorizes second arg',
            args: ['[replayer]', 'Unknown tag: web-component! This might cause issues.'],
            expected: 'Unknown tag: web-component',
        },
        {
            name: 'falls back to prefix when no non-prefix string exists',
            args: ['[replayer]'],
            expected: '[replayer]',
        },
        {
            name: 'prefers Error over prefix-like strings',
            args: ['[replayer]', '[warn]', new Error('something broke')],
            expected: 'something broke',
        },
        {
            name: 'handles rrweb-style array with plain message',
            args: ['[replayer]', 'Mutation target not found'],
            expected: 'Mutation target not found',
        },
    ])('$name', ({ args, expected }) => {
        expect(categorizeWarning(args)).toBe(expected)
    })
})

describe('isIgnoredWarning', () => {
    it.each([
        {
            name: 'ignores "Could not find node with id" warnings',
            category: 'Could not find node with id 1234',
            expected: true,
        },
        {
            name: 'does not ignore other warnings',
            category: 'Unknown tag: custom-element',
            expected: false,
        },
        {
            name: 'does not ignore empty string',
            category: '',
            expected: false,
        },
    ])('$name', ({ category, expected }) => {
        expect(isIgnoredWarning(category)).toBe(expected)
    })
})
