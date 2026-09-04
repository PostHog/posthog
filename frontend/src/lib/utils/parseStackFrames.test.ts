import { parseStackFrames } from './parseStackFrames'

describe('parseStackFrames', () => {
    it('parses a V8 stack bottom-up', () => {
        const stack = [
            'SyntaxError: Invalid or unexpected token',
            '    at loadApp (https://us.posthog.com/static/index.js:10:20)',
            '    at async boot (https://us.posthog.com/static/index.js:30:5)',
            '    at https://us.posthog.com/static/index.js:40:1',
        ].join('\n')

        expect(parseStackFrames(stack)).toEqual([
            {
                platform: 'web:javascript',
                filename: 'https://us.posthog.com/static/index.js',
                function: '?',
                lineno: 40,
                colno: 1,
                in_app: true,
            },
            {
                platform: 'web:javascript',
                filename: 'https://us.posthog.com/static/index.js',
                function: 'boot',
                lineno: 30,
                colno: 5,
                in_app: true,
            },
            {
                platform: 'web:javascript',
                filename: 'https://us.posthog.com/static/index.js',
                function: 'loadApp',
                lineno: 10,
                colno: 20,
                in_app: true,
            },
        ])
    })

    it('parses a Firefox and Safari stack, including anonymous frames', () => {
        const stack = [
            'loadApp@https://us.posthog.com/static/index.js:10:20',
            '@https://us.posthog.com/static/index.js:40:1',
        ].join('\n')

        expect(parseStackFrames(stack).map((frame) => [frame.function, frame.lineno])).toEqual([
            ['?', 40],
            ['loadApp', 10],
        ])
    })

    it.each([
        ['no stack', undefined],
        ['empty stack', ''],
        ['a stack with no frame the parser recognizes', 'TypeError: Load failed'],
    ])('returns no frame for %s', (_label, stack) => {
        expect(parseStackFrames(stack)).toEqual([])
    })

    it('caps a runaway stack at 50 frames', () => {
        const stack = Array.from(
            { length: 200 },
            (_, i) => `    at recurse (https://us.posthog.com/a.js:${i + 1}:1)`
        ).join('\n')

        expect(parseStackFrames(stack)).toHaveLength(50)
    })
})
