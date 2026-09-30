import { extractVariables, substituteVariables } from './playgroundTemplating'

describe('playgroundTemplating', () => {
    // The syntax must stay identical to the SDK compile helpers (@posthog/ai and
    // posthog-python): if these cases drift, a prompt saved from the playground
    // compiles differently in production.
    it.each([
        ['names allow word chars, dots and hyphens', 'Hi {{user.first-name}}, ask {{q_1}}', ['user.first-name', 'q_1']],
        ['repeats are deduped, order of first appearance kept', '{{b}} {{a}} {{b}}', ['b', 'a']],
        ['whitespace inside braces is literal, same as the SDKs', '{{ spaced }} {{x }}', []],
        ['empty and unclosed braces are literal', '{{}} {{unclosed and {b}', []],
    ])('extractVariables: %s', (_name, text, expected) => {
        expect(extractVariables(text)).toEqual(expected)
    })

    it('substitutes every occurrence and leaves unfilled placeholders intact', () => {
        expect(substituteVariables('{{a}} and {{b}} and {{a}}', { a: 'x' })).toBe('x and {{b}} and x')
        expect(substituteVariables('{{a}}', { a: '' })).toBe('{{a}}')
        // Object.prototype keys must not leak function source text into the prompt
        expect(substituteVariables('{{constructor}} {{toString}}', {})).toBe('{{constructor}} {{toString}}')
    })

    it('substitutes multiline JSON values containing replacement patterns literally', () => {
        // `$&` and `$'` are special in String.replace string form; a naive
        // implementation corrupts JSON values that contain them.
        const value = '{"amount": "$& USD",\n "note": "$\' end"}'
        expect(substituteVariables('data: {{payload}}', { payload: value })).toBe(`data: ${value}`)
    })
})
