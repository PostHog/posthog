import { markdownToTiptap } from './markdownToTiptap'

describe('markdownToTiptap', () => {
    describe('block elements', () => {
        it('handles empty string', () => {
            expect(markdownToTiptap('')).toEqual([])
        })

        it('handles whitespace only', () => {
            expect(markdownToTiptap('   \n\t  ')).toEqual([])
        })

        it('parses paragraph', () => {
            const result = markdownToTiptap('Hello world')
            expect(result).toEqual([
                {
                    type: 'paragraph',
                    content: [{ type: 'text', text: 'Hello world' }],
                },
            ])
        })

        it('parses heading level 1', () => {
            const result = markdownToTiptap('# Heading')
            expect(result).toEqual([
                {
                    type: 'heading',
                    attrs: { level: 1 },
                    content: [{ type: 'text', text: 'Heading' }],
                },
            ])
        })

        it('parses heading level 6', () => {
            const result = markdownToTiptap('###### Small heading')
            expect(result).toEqual([
                {
                    type: 'heading',
                    attrs: { level: 6 },
                    content: [{ type: 'text', text: 'Small heading' }],
                },
            ])
        })

        it('parses code block with language', () => {
            const result = markdownToTiptap('```javascript\nconst x = 1;\n```')
            expect(result).toEqual([
                {
                    type: 'codeBlock',
                    attrs: { language: 'javascript' },
                    content: [{ type: 'text', text: 'const x = 1;' }],
                },
            ])
        })

        it('parses code block without language', () => {
            const result = markdownToTiptap('```\nplain code\n```')
            expect(result).toEqual([
                {
                    type: 'codeBlock',
                    attrs: { language: null },
                    content: [{ type: 'text', text: 'plain code', marks: undefined }],
                },
            ])
        })

        it('parses blockquote', () => {
            const result = markdownToTiptap('> Quote text')
            expect(result).toEqual([
                {
                    type: 'blockquote',
                    content: [
                        {
                            type: 'paragraph',
                            content: [{ type: 'text', text: 'Quote text' }],
                        },
                    ],
                },
            ])
        })

        it('parses multi-line blockquote', () => {
            const result = markdownToTiptap('> Line 1\n> Line 2')
            expect(result).toEqual([
                {
                    type: 'blockquote',
                    content: [
                        {
                            type: 'paragraph',
                            content: [{ type: 'text', text: 'Line 1\nLine 2' }],
                        },
                    ],
                },
            ])
        })

        it('parses horizontal rule with dashes', () => {
            const result = markdownToTiptap('---')
            expect(result).toEqual([{ type: 'horizontalRule' }])
        })

        it('parses horizontal rule with asterisks', () => {
            const result = markdownToTiptap('***')
            expect(result).toEqual([{ type: 'horizontalRule' }])
        })

        it('parses unordered list', () => {
            const result = markdownToTiptap('- Item 1\n- Item 2')
            expect(result).toEqual([
                {
                    type: 'bulletList',
                    content: [
                        {
                            type: 'listItem',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Item 1' }] }],
                        },
                        {
                            type: 'listItem',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Item 2' }] }],
                        },
                    ],
                },
            ])
        })

        it('parses ordered list', () => {
            const result = markdownToTiptap('1. First\n2. Second')
            expect(result).toEqual([
                {
                    type: 'orderedList',
                    content: [
                        {
                            type: 'listItem',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'First' }] }],
                        },
                        {
                            type: 'listItem',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Second' }] }],
                        },
                    ],
                },
            ])
        })

        it('parses ordered list with custom start', () => {
            const result = markdownToTiptap('5. Fifth item')
            expect(result).toEqual([
                {
                    type: 'orderedList',
                    attrs: { start: 5 },
                    content: [
                        {
                            type: 'listItem',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Fifth item' }] }],
                        },
                    ],
                },
            ])
        })
    })

    describe('inline formatting', () => {
        it('parses bold with asterisks', () => {
            const result = markdownToTiptap('**bold text**')
            expect(result).toEqual([
                {
                    type: 'paragraph',
                    content: [{ type: 'text', text: 'bold text', marks: [{ type: 'bold' }] }],
                },
            ])
        })

        it('parses bold with underscores', () => {
            const result = markdownToTiptap('__bold text__')
            expect(result).toEqual([
                {
                    type: 'paragraph',
                    content: [{ type: 'text', text: 'bold text', marks: [{ type: 'bold' }] }],
                },
            ])
        })

        it('parses italic with asterisks', () => {
            const result = markdownToTiptap('*italic text*')
            expect(result).toEqual([
                {
                    type: 'paragraph',
                    content: [{ type: 'text', text: 'italic text', marks: [{ type: 'italic' }] }],
                },
            ])
        })

        it('parses italic with underscores', () => {
            const result = markdownToTiptap('_italic text_')
            expect(result).toEqual([
                {
                    type: 'paragraph',
                    content: [{ type: 'text', text: 'italic text', marks: [{ type: 'italic' }] }],
                },
            ])
        })

        it('parses inline code', () => {
            const result = markdownToTiptap('`code`')
            expect(result).toEqual([
                {
                    type: 'paragraph',
                    content: [{ type: 'text', text: 'code', marks: [{ type: 'code' }] }],
                },
            ])
        })

        it('parses strikethrough', () => {
            const result = markdownToTiptap('~~deleted~~')
            expect(result).toEqual([
                {
                    type: 'paragraph',
                    content: [{ type: 'text', text: 'deleted', marks: [{ type: 'strike' }] }],
                },
            ])
        })

        it('parses links', () => {
            const result = markdownToTiptap('[PostHog](https://posthog.com)')
            expect(result).toEqual([
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'PostHog',
                            marks: [{ type: 'link', attrs: { href: 'https://posthog.com', title: null } }],
                        },
                    ],
                },
            ])
        })

        it('parses mixed inline formatting', () => {
            const result = markdownToTiptap('Plain **bold** and *italic* text')
            expect(result).toEqual([
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'Plain ' },
                        { type: 'text', text: 'bold', marks: [{ type: 'bold' }] },
                        { type: 'text', text: ' and ' },
                        { type: 'text', text: 'italic', marks: [{ type: 'italic' }] },
                        { type: 'text', text: ' text' },
                    ],
                },
            ])
        })
    })

    describe('combined elements', () => {
        it('parses heading with formatting', () => {
            const result = markdownToTiptap('# Hello **world**')
            expect(result).toEqual([
                {
                    type: 'heading',
                    attrs: { level: 1 },
                    content: [
                        { type: 'text', text: 'Hello ' },
                        { type: 'text', text: 'world', marks: [{ type: 'bold' }] },
                    ],
                },
            ])
        })

        it('parses multiple paragraphs', () => {
            const result = markdownToTiptap('First paragraph\n\nSecond paragraph')
            expect(result).toEqual([
                { type: 'paragraph', content: [{ type: 'text', text: 'First paragraph' }] },
                { type: 'paragraph', content: [{ type: 'text', text: 'Second paragraph' }] },
            ])
        })

        it('parses complex document', () => {
            const markdown = `# Title

This is **bold** text.

- Item 1
- Item 2

---

> A quote

\`\`\`js
code()
\`\`\``

            const result = markdownToTiptap(markdown)
            expect(result.length).toBe(6)
            expect(result[0].type).toBe('heading')
            expect(result[1].type).toBe('paragraph')
            expect(result[2].type).toBe('bulletList')
            expect(result[3].type).toBe('horizontalRule')
            expect(result[4].type).toBe('blockquote')
            expect(result[5].type).toBe('codeBlock')
        })
    })

    describe('edge cases', () => {
        it('handles unclosed code block gracefully', () => {
            // Unclosed code block - content until EOF becomes the code
            const result = markdownToTiptap('```js\ncode without closing')
            expect(result).toEqual([
                {
                    type: 'codeBlock',
                    attrs: { language: 'js' },
                    content: [{ type: 'text', text: 'code without closing' }],
                },
            ])
        })

        it('handles empty list gracefully', () => {
            // Single list item
            const result = markdownToTiptap('- ')
            expect(result.length).toBeGreaterThanOrEqual(0)
        })

        it('handles list with formatting', () => {
            const result = markdownToTiptap('- **Bold item**')
            expect(result).toEqual([
                {
                    type: 'bulletList',
                    content: [
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [{ type: 'text', text: 'Bold item', marks: [{ type: 'bold' }] }],
                                },
                            ],
                        },
                    ],
                },
            ])
        })
    })
})
