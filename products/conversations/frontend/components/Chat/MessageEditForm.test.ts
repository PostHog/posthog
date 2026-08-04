import type { ChatMessage } from '../../types'
import { initialEditorContent } from './MessageEditForm'

function note(overrides: Partial<ChatMessage>): ChatMessage {
    return {
        id: 'note-1',
        content: '',
        authorType: 'human',
        authorName: 'Agent',
        createdAt: '2026-01-01T00:00:00Z',
        isPrivate: true,
        ...overrides,
    }
}

function seededDoc(content: string): string {
    return JSON.stringify(initialEditorContent(note({ content })))
}

describe('initialEditorContent', () => {
    // Notes posted through the ticket reply API or carried in by an import hold markdown in
    // `content` with no rich content. Loading that string as one literal text node meant the editor
    // showed raw syntax and the save escaped it, so `**urgent**` was stored as `\*\*urgent\*\*` and
    // stopped rendering as bold. The markdown has to arrive as real marks and nodes.
    test.each([
        ['emphasis', '**urgent**: card expired', '"bold"', '**'],
        ['a bullet list', '- refund issued\n- card expired', '"bulletList"', '- refund'],
        ['a numbered list', '1. check the card\n2. issue the refund', '"orderedList"', '1. check'],
        ['a link', 'see [the docs](https://posthog.com/docs)', '"link"', '[the docs]'],
        ['inline code', 'run `identify()` first', '"code"', '`identify'],
    ])('loads %s as editor structure, not literal syntax', (_name, content, expectedType, literalSyntax) => {
        const doc = seededDoc(content)

        expect(doc).toContain(expectedType)
        expect(doc).not.toContain(literalSyntax)
    })

    it('keeps paragraphs separate', () => {
        const doc = initialEditorContent(note({ content: 'Checked their billing.\n\nThe charge failed.' }))

        expect(doc.content).toHaveLength(2)
    })

    it('prefers stored rich content over parsing the markdown', () => {
        const richContent = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'hi' }] }] }

        expect(initialEditorContent(note({ content: 'ignored', richContent }))).toBe(richContent)
    })
})
