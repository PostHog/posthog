import { JSONContent } from '@tiptap/core'

import {
    TEXT_CARD_MARKDOWN_EXTENSIONS,
    TEXT_CARD_MARKDOWN_READONLY_EXTENSIONS,
    textCardConverter,
} from './textCardMarkdown'

describe('textCardMarkdown', () => {
    it.each([undefined, null, '', '   \n\t '])('returns an empty doc for blank markdown: %p', (markdown) => {
        expect(textCardConverter.markdownToDoc(markdown)).toEqual({
            type: 'doc',
            content: [{ type: 'paragraph' }],
        })
    })

    it('serializes an empty tiptap doc to an empty markdown string', () => {
        expect(
            textCardConverter.docToMarkdown({
                type: 'doc',
                content: [{ type: 'paragraph' }],
            })
        ).toBe('')
    })

    it('parses legacy markdown into tiptap content', () => {
        const doc = textCardConverter.markdownToDoc('# Heading\n\n- Item 1\n- Item 2')
        expect(doc.type).toBe('doc')
        expect(doc.content?.[0]).toMatchObject({ type: 'heading', attrs: { level: 1 } })
        expect(doc.content?.[1]).toMatchObject({ type: 'bulletList' })
    })

    it('serializes tiptap content back to markdown', () => {
        const markdown = textCardConverter.docToMarkdown(
            textCardConverter.markdownToDoc('**bold**\n\n1. first\n2. second\n\n![img](https://example.com/image.png)')
        )

        expect(markdown).toContain('**bold**')
        expect(markdown).toContain('1. first')
        expect(markdown).toContain('2. second')
        expect(markdown).toContain('![img](https://example.com/image.png)')
    })

    it('parses and serializes strikethrough markdown', () => {
        const input = '~~crossed~~ and **bold**'
        const doc = textCardConverter.markdownToDoc(input)
        const paragraph = doc.content?.[0]
        expect(paragraph?.type).toBe('paragraph')
        const strikeText = paragraph?.content?.find(
            (n) => n.type === 'text' && n.marks?.some((m) => m.type === 'strike')
        )
        expect(strikeText).toMatchObject({ type: 'text', text: 'crossed' })
        expect(textCardConverter.docToMarkdown(doc)).toContain('~~crossed~~')
    })

    it('preserves resized image dimensions when serializing markdown', () => {
        const doc: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'image',
                    attrs: {
                        src: 'https://example.com/image.png',
                        alt: 'img',
                        width: 320,
                        height: 180,
                    },
                },
            ],
        }

        const markdown = textCardConverter.docToMarkdown(doc)
        const roundTripDoc = textCardConverter.markdownToDoc(markdown)
        const imageNode = roundTripDoc.content?.[0]

        expect(markdown).toContain('<img ')
        expect(markdown).toContain('width="320"')
        expect(markdown).toContain('height="180"')
        expect(imageNode?.type).toBe('image')
        expect(String(imageNode?.attrs?.width)).toBe('320')
        expect(String(imageNode?.attrs?.height)).toBe('180')
    })

    it.each([
        '# Heading\n\nRegular paragraph',
        '**bold** _italic_ `code`',
        '1. first\n2. second',
        '- [x] done\n- [ ] pending',
        '![img](https://example.com/test.png)',
    ])('identifies round-trip safe markdown: %p', (markdown) => {
        expect(textCardConverter.isRoundTripSafe(markdown)).toBe(true)
    })

    it('does not append storage metadata markers to markdown output', () => {
        const richDoc: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    attrs: { textAlign: 'center' },
                    content: [
                        { type: 'text', text: 'underlined', marks: [{ type: 'underline' }] },
                        { type: 'text', text: ' ' },
                        { type: 'text', text: 'inline code', marks: [{ type: 'code' }] },
                    ],
                },
                {
                    type: 'codeBlock',
                    attrs: { language: null },
                    content: [{ type: 'text', text: 'const a = 1;' }],
                },
            ],
        }

        const markdown = textCardConverter.docToMarkdown(richDoc)
        const roundTripDoc = textCardConverter.markdownToDoc(markdown)

        expect(markdown).toContain('++underlined++')
        expect(markdown).toContain('`inline code`')
        expect(markdown).toContain('```')
        expect(markdown).not.toContain('<!--ph-text-card-doc:')
        expect(roundTripDoc).not.toEqual(richDoc)
    })

    it.each([['bold'], ['italic'], ['strike']])('keeps inline code innermost when a text node is also %s', (mark) => {
        // A styled span ending on an inline code snippet used to serialize with the
        // closing markers in the wrong order (e.g. **start `snippet**`), corrupting the card
        const doc: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'start ', marks: [{ type: mark }] },
                        { type: 'text', text: 'snippet', marks: [{ type: mark }, { type: 'code' }] },
                    ],
                },
            ],
        }

        const markdown = textCardConverter.docToMarkdown(doc)
        const reparsedSnippet = textCardConverter
            .markdownToDoc(markdown)
            .content?.[0]?.content?.find((node) => node.marks?.some((m) => m.type === 'code'))

        expect(markdown).toContain('`snippet`')
        expect(reparsedSnippet?.text).toBe('snippet')
        expect(reparsedSnippet?.marks?.map((m) => m.type).sort()).toEqual(['code', mark].sort())
        expect(textCardConverter.isRoundTripSafe(markdown)).toBe(true)
    })

    it('supports underline markdown round-trip', () => {
        const markdown = '++underlined++'
        const doc = textCardConverter.markdownToDoc(markdown)
        const serialized = textCardConverter.docToMarkdown(doc)

        expect(serialized).toContain('++underlined++')
    })

    it.each([
        ['plain text', 'BIG WINS', 'chrome', 'chrome', 'medium', 'medium'],
        ['text with html-sensitive characters', 'Q3 <wins> & *losses*', 'neon', 'neon', 'medium', 'medium'],
        ['unknown style id normalized to default', 'hello', 'clippy-3000', 'rainbow', 'medium', 'medium'],
        ['a non-default size', 'HUGE', 'fire', 'fire', 'large', 'large'],
        ['unknown size normalized to default', 'hello', 'ice', 'ice', 'gigantic', 'medium'],
    ])('round-trips word art with %s', (_name, text, style, expectedStyle, size, expectedSize) => {
        const doc: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'before ' },
                        { type: 'wordArt', attrs: { text, style, size } },
                        { type: 'text', text: ' after' },
                    ],
                },
            ],
        }

        const markdown = textCardConverter.docToMarkdown(doc)
        const roundTripDoc = textCardConverter.markdownToDoc(markdown)
        const wordArtNode = roundTripDoc.content?.[0]?.content?.find((node) => node.type === 'wordArt')

        expect(markdown).toContain(`<span data-word-art="${expectedStyle}"`)
        if (expectedSize === 'medium') {
            expect(markdown).not.toContain('data-word-art-size')
        } else {
            expect(markdown).toContain(`data-word-art-size="${expectedSize}"`)
        }
        expect(wordArtNode?.attrs).toEqual({ text, style: expectedStyle, size: expectedSize })
        expect(textCardConverter.isRoundTripSafe(markdown)).toBe(true)
    })

    it('uses non-clickable links while editing and clickable links in readonly', () => {
        const editableLink = TEXT_CARD_MARKDOWN_EXTENSIONS.find((extension) => extension.name === 'link')
        const readonlyLink = TEXT_CARD_MARKDOWN_READONLY_EXTENSIONS.find((extension) => extension.name === 'link')
        const editableOptions = editableLink?.options as { openOnClick?: boolean } | undefined
        const readonlyOptions = readonlyLink?.options as { openOnClick?: boolean } | undefined

        expect(editableOptions?.openOnClick).toBe(false)
        expect(readonlyOptions?.openOnClick).toBe(true)
    })
})
