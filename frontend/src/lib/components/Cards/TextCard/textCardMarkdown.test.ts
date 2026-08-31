import { JSONContent } from '@tiptap/core'

import {
    TEXT_CARD_MARKDOWN_EXTENSIONS,
    TEXT_CARD_MARKDOWN_READONLY_EXTENSIONS,
    textCardConverter,
} from './textCardMarkdown'

describe('textCardMarkdown', () => {
    const codeSpanTextNode = (markdown: string): JSONContent | undefined =>
        textCardConverter.markdownToDoc(markdown).content?.[0]?.content?.[0]
    const linkHref = (node: JSONContent | undefined): unknown =>
        node?.marks?.find((mark) => mark.type === 'link')?.attrs?.href

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
            .content?.[0]?.content?.find((node: JSONContent) =>
                node.marks?.some((m: { type: string }) => m.type === 'code')
            )

        expect(markdown).toContain('`snippet`')
        expect(reparsedSnippet?.text).toBe('snippet')
        expect(reparsedSnippet?.marks?.map((m: { type: string }) => m.type).sort()).toEqual(['code', mark].sort())
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

    // A destination in angle brackets is markdown syntax, so the brackets must not reach the href.
    // A destination holding balanced parens must survive whole, which a naive match truncates.
    it.each([
        ['a plain destination', '`[table_name](https://us.posthog.com/x)`', 'table_name', 'https://us.posthog.com/x'],
        [
            'a destination in angle brackets',
            '`[table_name](<https://us.posthog.com/x>)`',
            'table_name',
            'https://us.posthog.com/x',
        ],
        [
            'a destination holding balanced parens',
            '`[wiki](https://en.wikipedia.org/wiki/Hog_(disambiguation))`',
            'wiki',
            'https://en.wikipedia.org/wiki/Hog_(disambiguation)',
        ],
        ['a relative path', '`[insights](/project/2/insights)`', 'insights', '/project/2/insights'],
        ['mailto', '`[email us](mailto:hey@example.com)`', 'email us', 'mailto:hey@example.com'],
        ['tel', '`[call us](tel:+15551234567)`', 'call us', 'tel:+15551234567'],
    ])('links a code span containing %s', (_, markdown, expectedText, expectedHref) => {
        const textNode = codeSpanTextNode(markdown)

        expect(textNode).toMatchObject({ type: 'text', text: expectedText })
        expect(textNode?.marks?.map((m) => m.type).sort()).toEqual(['code', 'link'])
        expect(linkHref(textNode)).toBe(expectedHref)
    })

    it('round-trips a link written inside a code span unchanged', () => {
        const source = '`[table_name](https://us.posthog.com/x)`'
        const doc = textCardConverter.markdownToDoc(source)
        const markdown = textCardConverter.docToMarkdown(doc)

        // The author's own markdown comes back, so saving a card does not rewrite what they typed.
        expect(markdown).toBe(source)
        expect(textCardConverter.markdownToDoc(markdown)).toEqual(doc)
    })

    it('keeps the target href when a linked code span label is a URL', () => {
        // `[`https://label.example`](https://target.example)` already parses to a single code+link
        // node; promoting it again used to append a second link mark and rewrite the href to the label URL.
        const markdown = '[`https://label.example`](https://target.example)'
        const doc = textCardConverter.markdownToDoc(markdown)
        const textNode = doc.content?.[0]?.content?.[0]

        expect(textNode?.marks?.filter((m) => m.type === 'link')).toHaveLength(1)
        expect(textNode?.marks?.find((m) => m.type === 'link')?.attrs?.href).toBe('https://target.example')
        expect(textCardConverter.docToMarkdown(doc)).toBe('[`https://label.example`](https://target.example)')
    })

    // Promotion writes the matched destination onto the href itself, so it applies the link mark's
    // own protocol allowlist. A scheme the mark would refuse stays plain text with only a `code`
    // mark. A second, narrower list here would silently refuse destinations the editor accepts
    // everywhere else.
    it.each([
        ['a javascript scheme', "`[click me](javascript:document.location='https://evil.example')`"],
        ['a data scheme', '`[click me](data:text/html,hi)`'],
        ['a vbscript scheme', '`[click me](vbscript:msgbox)`'],
        ['no link syntax at all', '`SELECT * FROM events`'],
        // A code span can sit inside a link already, so its bare text is left alone.
        ['a bare URL', '`https://us.posthog.com/x`'],
        // Emphasis characters are literal in code and must not become marks.
        ['underscores and asterisks', '`a_b_c and *x*`'],
    ])('leaves a code span with %s as plain code', (_, markdown) => {
        const textNode = codeSpanTextNode(markdown)

        // The text keeps the backticked content verbatim, so nothing was rewritten to a link label.
        expect(textNode).toMatchObject({ type: 'text', text: markdown.slice(1, -1) })
        expect(textNode?.marks?.map((m) => m.type)).toEqual(['code'])
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
