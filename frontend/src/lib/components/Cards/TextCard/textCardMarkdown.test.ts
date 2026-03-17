import { isTextCardMarkdownRoundTripSafe, markdownToTextCardDoc, textCardDocToMarkdown } from './textCardMarkdown'

describe('textCardMarkdown', () => {
    it.each([undefined, null, '', '   \n\t '])('returns an empty doc for blank markdown: %p', (markdown) => {
        expect(markdownToTextCardDoc(markdown)).toEqual({
            type: 'doc',
            content: [{ type: 'paragraph' }],
        })
    })

    it('parses legacy markdown into tiptap content', () => {
        const doc = markdownToTextCardDoc('# Heading\n\n- Item 1\n- Item 2')
        expect(doc.type).toBe('doc')
        expect(doc.content?.[0]).toMatchObject({ type: 'heading', attrs: { level: 1 } })
        expect(doc.content?.[1]).toMatchObject({ type: 'bulletList' })
    })

    it('serializes tiptap content back to markdown', () => {
        const markdown = textCardDocToMarkdown(
            markdownToTextCardDoc('**bold**\n\n1. first\n2. second\n\n![img](https://example.com/image.png)')
        )

        expect(markdown).toContain('**bold**')
        expect(markdown).toContain('1. first')
        expect(markdown).toContain('2. second')
        expect(markdown).toContain('![img](https://example.com/image.png)')
    })

    it.each([
        '# Heading\n\nRegular paragraph',
        '**bold** _italic_ `code`',
        '1. first\n2. second',
        '- [x] done\n- [ ] pending',
        '![img](https://example.com/test.png)',
        '<div>raw html</div>',
    ])('identifies round-trip safe markdown: %p', (markdown) => {
        expect(isTextCardMarkdownRoundTripSafe(markdown)).toBe(true)
    })

    it.each(['| a | b |\n| - | - |\n| c | d |'])('identifies markdown requiring legacy fallback: %p', (markdown) => {
        expect(isTextCardMarkdownRoundTripSafe(markdown)).toBe(false)
    })
})
