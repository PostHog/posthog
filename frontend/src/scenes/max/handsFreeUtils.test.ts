import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'

import { buildSpokenText, stripMarkdown, summariseAssistantThread } from './handsFreeUtils'

type StubMessage = Parameters<typeof summariseAssistantThread>[0][number]

const human = (content = 'hi'): StubMessage => ({ type: AssistantMessageType.Human, content })
const ai = (content: string): StubMessage => ({ type: AssistantMessageType.Assistant, content })
const viz = (): StubMessage => ({ type: AssistantMessageType.Visualization })
const multiViz = (): StubMessage => ({ type: AssistantMessageType.MultiVisualization })
const artifact = (): StubMessage => ({ type: AssistantMessageType.Artifact })

describe('handsFreeUtils', () => {
    describe('summariseAssistantThread()', () => {
        it('returns the assistant prose message and no viz suffix when none present', () => {
            const result = summariseAssistantThread([human(), ai('here is the answer')])
            expect(result).toEqual({ text: 'here is the answer', vizCount: 0 })
        })

        it.each([
            ['Visualization', [ai('see chart'), viz()], 1],
            ['MultiVisualization', [ai('see charts'), multiViz()], 1],
            ['Artifact', [ai('see notebook'), artifact()], 1],
            ['mix of viz types', [ai('see charts'), viz(), multiViz(), artifact()], 3],
        ] as const)('counts %s blocks since the last human message', (_label, tail, expectedCount) => {
            const result = summariseAssistantThread([human(), ...tail])
            expect(result.vizCount).toBe(expectedCount)
        })

        it('only counts messages produced after the most recent human message', () => {
            const result = summariseAssistantThread([
                human('first ask'),
                ai('old answer'),
                viz(),
                human('second ask'),
                ai('new answer'),
                viz(),
            ])
            expect(result).toEqual({ text: 'new answer', vizCount: 1 })
        })

        it('returns the LATEST prose message when the assistant emits several in one turn', () => {
            const result = summariseAssistantThread([
                human(),
                ai('first part of the answer'),
                ai('second part of the answer'),
                ai('final summary'),
            ])
            expect(result).toEqual({ text: 'final summary', vizCount: 0 })
        })

        it('returns empty text when only viz messages followed the human turn', () => {
            const result = summariseAssistantThread([human(), viz(), multiViz()])
            expect(result).toEqual({ text: '', vizCount: 2 })
        })

        it('returns empty text and zero count when thread has no assistant turn', () => {
            const result = summariseAssistantThread([human()])
            expect(result).toEqual({ text: '', vizCount: 0 })
        })

        it('handles a thread that never had a human turn (e.g. agent-initiated)', () => {
            const result = summariseAssistantThread([ai('hello there'), viz()])
            expect(result).toEqual({ text: 'hello there', vizCount: 1 })
        })
    })

    describe('buildSpokenText()', () => {
        it.each([
            [{ text: 'just words', vizCount: 0 }, 'just words'],
            [{ text: 'words', vizCount: 1 }, "words I've added 1 chart to the chat."],
            [{ text: 'words', vizCount: 3 }, "words I've added 3 charts to the chat."],
            [{ text: '', vizCount: 2 }, "I've added 2 charts to the chat."],
            [{ text: '', vizCount: 0 }, ''],
        ])('builds %p -> %p', (summary, expected) => {
            expect(buildSpokenText(summary)).toBe(expected)
        })
    })

    describe('stripMarkdown()', () => {
        it.each([
            ['# Heading', 'Heading'],
            ['**bold text**', 'bold text'],
            ['_italic_', 'italic'],
            ['*emphasised*', 'emphasised'],
            ['~~struck~~', 'struck'],
            ['`inline code`', 'inline code'],
            ['1. first item\n2. second item', 'first item second item'],
            ['- bullet\n- bullet', 'bullet bullet'],
            ['[link text](https://example.com)', 'link text'],
            ['![alt](https://example.com/x.png) caption', ' caption'],
            ['> quoted line', 'quoted line'],
        ])('strips %p -> %p', (input, expected) => {
            expect(stripMarkdown(input)).toBe(expected)
        })

        it('leaves identifiers like foo_bar_baz alone (bold underscore guard)', () => {
            expect(stripMarkdown('the var is foo_bar_baz here')).toBe('the var is foo_bar_baz here')
        })

        it('omits fenced code blocks rather than reading them verbatim', () => {
            const input = 'before\n```ts\nconst x = 1\n```\nafter'
            expect(stripMarkdown(input)).toContain('code block omitted')
            expect(stripMarkdown(input)).not.toContain('const x')
        })

        it('strips table separator rows and pipes', () => {
            const input = '| col a | col b |\n| --- | --- |\n| one | two |'
            const result = stripMarkdown(input)
            expect(result).not.toContain('---')
            expect(result).not.toContain('|')
            expect(result).toContain('col a')
            expect(result).toContain('one')
        })

        it('collapses runs of whitespace so TTS does not over-pause', () => {
            expect(stripMarkdown('one\n\n\ntwo')).toBe('one two')
        })
    })
})
