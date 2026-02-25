import type { JSONContent } from '@tiptap/core'

import type { ProductTourStep } from '~/types'

import {
    generateStepHtml,
    generateTranslationsHtml,
    prepareStepForRender,
    prepareStepsForRender,
} from './generateStepHtml'

function makeStep(overrides: Partial<ProductTourStep> & { content: ProductTourStep['content'] }): ProductTourStep {
    return { id: '1', type: 'modal', ...overrides }
}

jest.mock('@tiptap/html', () => ({
    generateHTML: jest.fn((content: JSONContent) => {
        if (!content?.content?.length) {
            return ''
        }

        const renderText = (textNode: any): string => {
            let text = textNode.text || ''
            for (const mark of textNode.marks || []) {
                if (mark.type === 'link') {
                    text = `<a href="${mark.attrs?.href || ''}">${text}</a>`
                }
                if (mark.type === 'bold') {
                    text = `<strong>${text}</strong>`
                }
                if (mark.type === 'italic') {
                    text = `<em>${text}</em>`
                }
            }
            return text
        }

        const renderNode = (node: any): string => {
            const innerContent = (node.content || [])
                .map((c: any) => (c.type === 'text' ? renderText(c) : renderNode(c)))
                .join('')

            switch (node.type) {
                case 'paragraph':
                    return `<p>${innerContent}</p>`
                case 'heading':
                    return `<h${node.attrs?.level || 1}>${innerContent}</h${node.attrs?.level || 1}>`
                case 'codeBlock':
                    return `<pre><code class="language-${node.attrs?.language || 'plaintext'}">${innerContent}</code></pre>`
                case 'blockquote':
                    return `<blockquote>${innerContent}</blockquote>`
                case 'bulletList':
                    return `<ul>${innerContent}</ul>`
                case 'listItem':
                    return `<li>${innerContent}</li>`
                default:
                    return innerContent
            }
        }

        return content.content.map(renderNode).join('')
    }),
}))

jest.mock('@tiptap/starter-kit', () => ({ __esModule: true, default: { configure: () => ({}) } }))
jest.mock('@tiptap/extension-code-block-lowlight', () => ({ __esModule: true, default: { configure: () => ({}) } }))
jest.mock('@tiptap/extension-image', () => ({ Image: { configure: () => ({}) } }))
jest.mock('@tiptap/extension-link', () => ({ Link: { configure: () => ({}) } }))
jest.mock('@tiptap/extension-underline', () => ({ Underline: {} }))
jest.mock('./EmbedExtension', () => ({ EmbedExtension: {} }))

jest.mock('lowlight', () => ({
    createLowlight: () => ({
        register: jest.fn(),
        registered: (lang: string) => lang === 'javascript',
        highlight: jest.fn(() => ({ type: 'root', children: [{ type: 'text', value: 'highlighted-code' }] })),
        highlightAuto: jest.fn(() => ({ type: 'root', children: [{ type: 'text', value: 'auto-highlighted' }] })),
    }),
    common: {},
}))

jest.mock('hast-util-to-html', () => ({
    toHtml: (node: { children: Array<{ value: string }> }) => node.children.map((c) => c.value).join(''),
}))

describe('generateStepHtml', () => {
    it.each([
        ['null content', null, ''],
        ['empty doc', { type: 'doc', content: [] }, ''],
        [
            'paragraph',
            { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] }] },
            '<p>Hello</p>',
        ],
        [
            'h1',
            {
                type: 'doc',
                content: [{ type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'Title' }] }],
            },
            '<h1>Title</h1>',
        ],
        [
            'h2',
            {
                type: 'doc',
                content: [{ type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: 'Subtitle' }] }],
            },
            '<h2>Subtitle</h2>',
        ],
        [
            'h3',
            {
                type: 'doc',
                content: [{ type: 'heading', attrs: { level: 3 }, content: [{ type: 'text', text: 'Section' }] }],
            },
            '<h3>Section</h3>',
        ],
        [
            'link',
            {
                type: 'doc',
                content: [
                    {
                        type: 'paragraph',
                        content: [
                            {
                                type: 'text',
                                marks: [{ type: 'link', attrs: { href: 'https://posthog.com' } }],
                                text: 'PostHog',
                            },
                        ],
                    },
                ],
            },
            '<p><a href="https://posthog.com">PostHog</a></p>',
        ],
        [
            'bold text',
            {
                type: 'doc',
                content: [{ type: 'paragraph', content: [{ type: 'text', marks: [{ type: 'bold' }], text: 'Bold' }] }],
            },
            '<p><strong>Bold</strong></p>',
        ],
        [
            'italic text',
            {
                type: 'doc',
                content: [
                    { type: 'paragraph', content: [{ type: 'text', marks: [{ type: 'italic' }], text: 'Italic' }] },
                ],
            },
            '<p><em>Italic</em></p>',
        ],
        [
            'heading then paragraph',
            {
                type: 'doc',
                content: [
                    { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'Title' }] },
                    { type: 'paragraph', content: [{ type: 'text', text: 'Body text' }] },
                ],
            },
            '<h1>Title</h1><p>Body text</p>',
        ],
        [
            'multiple paragraphs',
            {
                type: 'doc',
                content: [
                    { type: 'paragraph', content: [{ type: 'text', text: 'First' }] },
                    { type: 'paragraph', content: [{ type: 'text', text: 'Second' }] },
                ],
            },
            '<p>First</p><p>Second</p>',
        ],
        [
            'blockquote',
            {
                type: 'doc',
                content: [
                    {
                        type: 'blockquote',
                        content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Quote' }] }],
                    },
                ],
            },
            '<blockquote><p>Quote</p></blockquote>',
        ],
        [
            'bullet list',
            {
                type: 'doc',
                content: [
                    {
                        type: 'bulletList',
                        content: [
                            {
                                type: 'listItem',
                                content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Item' }] }],
                            },
                        ],
                    },
                ],
            },
            '<ul><li><p>Item</p></li></ul>',
        ],
        [
            'bold link',
            {
                type: 'doc',
                content: [
                    {
                        type: 'paragraph',
                        content: [
                            {
                                type: 'text',
                                marks: [{ type: 'bold' }, { type: 'link', attrs: { href: 'https://posthog.com' } }],
                                text: 'Click here',
                            },
                        ],
                    },
                ],
            },
            '<p><a href="https://posthog.com"><strong>Click here</strong></a></p>',
        ],
    ])('handles %s', (_name, content, expected) => {
        expect(generateStepHtml(content as JSONContent | null)).toBe(expected)
    })

    it('applies syntax highlighting to code blocks', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'codeBlock',
                    attrs: { language: 'javascript' },
                    content: [{ type: 'text', text: 'const x = 1' }],
                },
            ],
        }

        const result = generateStepHtml(content)

        expect(result).toBe('<pre><code class="language-javascript">highlighted-code</code></pre>')
    })

    it('uses auto-highlight for unregistered languages', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                { type: 'codeBlock', attrs: { language: 'rust' }, content: [{ type: 'text', text: 'fn main()' }] },
            ],
        }

        const result = generateStepHtml(content)

        expect(result).toBe('<pre><code class="language-rust">auto-highlighted</code></pre>')
    })
})

const paragraph = (text: string): Record<string, any> => ({
    type: 'doc',
    content: [{ type: 'paragraph', content: [{ type: 'text', text }] }],
})

describe('prepareStepForRender', () => {
    it('adds contentHtml to step with content', () => {
        const result = prepareStepForRender(makeStep({ content: paragraph('Test') }))

        expect(result.contentHtml).toBe('<p>Test</p>')
    })

    it('returns undefined contentHtml for null content', () => {
        expect(prepareStepForRender(makeStep({ content: null })).contentHtml).toBeUndefined()
    })

    it('generates contentHtml for each translation with content', () => {
        const step = makeStep({
            content: paragraph('Hello'),
            translations: {
                fr: { content: paragraph('Bonjour') },
                de: { content: paragraph('Hallo') },
            },
        })

        const result = prepareStepForRender(step)

        expect(result.contentHtml).toBe('<p>Hello</p>')
        expect(result.translations?.fr.contentHtml).toBe('<p>Bonjour</p>')
        expect(result.translations?.de.contentHtml).toBe('<p>Hallo</p>')
    })

    it('preserves non-content translation fields', () => {
        const step = makeStep({
            content: paragraph('Hello'),
            translations: {
                fr: {
                    content: paragraph('Bonjour'),
                    buttons: { primary: { text: 'Suivant' } },
                    survey: { questionText: 'Comment ça va?' },
                },
            },
        })

        const result = prepareStepForRender(step)

        expect(result.translations?.fr.buttons).toEqual({ primary: { text: 'Suivant' } })
        expect(result.translations?.fr.survey).toEqual({ questionText: 'Comment ça va?' })
    })

    it('skips contentHtml for translations without content', () => {
        const step = makeStep({
            content: paragraph('Hello'),
            translations: {
                fr: { buttons: { primary: { text: 'Suivant' } } },
            },
        })

        const result = prepareStepForRender(step)

        expect(result.translations?.fr.contentHtml).toBeUndefined()
        expect(result.translations?.fr.buttons).toEqual({ primary: { text: 'Suivant' } })
    })

    it('does not add translations key when step has none', () => {
        const result = prepareStepForRender(makeStep({ content: paragraph('Hello') }))

        expect(result).not.toHaveProperty('translations')
    })
})

describe('prepareStepsForRender', () => {
    it('processes array of steps', () => {
        const results = prepareStepsForRender([
            makeStep({ id: '1', content: paragraph('A') }),
            makeStep({ id: '2', content: null }),
        ])

        expect(results).toHaveLength(2)
        expect(results[0].contentHtml).toBe('<p>A</p>')
        expect(results[1].contentHtml).toBeUndefined()
    })
})

describe('generateTranslationsHtml', () => {
    it.each([
        [
            'generates contentHtml for each language',
            { fr: { content: paragraph('Bonjour') }, de: { content: paragraph('Hallo') } },
            { fr: '<p>Bonjour</p>', de: '<p>Hallo</p>' },
        ],
        [
            'skips contentHtml when content is missing',
            { fr: { buttons: { primary: { text: 'Suivant' } } } },
            { fr: undefined },
        ],
        ['handles null content', { fr: { content: null } }, { fr: undefined }],
    ])('%s', (_name, translations, expectedHtml) => {
        const result = generateTranslationsHtml(translations as any)

        for (const [lang, expected] of Object.entries(expectedHtml)) {
            expect(result[lang].contentHtml).toBe(expected)
        }
    })
})
