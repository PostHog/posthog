import { JSONContent } from '@tiptap/core'

import { applyTemplateVariables, applyTemplateVariablesToRichContent } from './templateVariables'

describe('templateVariables', () => {
    it.each([
        ['Hi {{customer.name}}!', { 'customer.name': 'Ada' }, 'Hi Ada!'],
        ['Ticket #{{ ticket.number }}', { 'ticket.number': '42' }, 'Ticket #42'],
        // Unknown or unset tokens resolve to empty so no raw {{...}} reaches the customer.
        ['Hi {{customer.name}}', {}, 'Hi '],
        ['{{unknown.token}} done', { 'customer.name': 'Ada' }, ' done'],
    ])('applyTemplateVariables(%j) fills known tokens and blanks the rest', (text, values, expected) => {
        expect(applyTemplateVariables(text as string, values as Record<string, string>)).toBe(expected)
    })

    it('substitutes variables in every text node of a rich-content tree without mutating the input', () => {
        const input: JSONContent = {
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hey {{customer.name}}' }] }],
        }

        const result = applyTemplateVariablesToRichContent(input, { 'customer.name': 'Ada' })

        expect(result.content?.[0].content?.[0].text).toBe('Hey Ada')
        // Original tree is untouched.
        expect(input.content?.[0].content?.[0].text).toBe('Hey {{customer.name}}')
    })

    // Regression: a token inside a link href (a mark attr) must be substituted too, else the raw
    // {{...}} ships to the customer as a broken URL.
    it('substitutes variables in mark and node attributes, not just text', () => {
        const input: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'Track it',
                            marks: [{ type: 'link', attrs: { href: 'https://ph.test/t/{{ticket.number}}' } }],
                        },
                    ],
                },
                {
                    type: 'image',
                    attrs: { src: 'https://ph.test/{{ticket.number}}.png', alt: 'ticket {{ticket.number}}' },
                },
            ],
        }

        const result = applyTemplateVariablesToRichContent(input, { 'ticket.number': '42' })

        expect(result.content?.[0].content?.[0].marks?.[0].attrs?.href).toBe('https://ph.test/t/42')
        expect(result.content?.[1].attrs?.src).toBe('https://ph.test/42.png')
        expect(result.content?.[1].attrs?.alt).toBe('ticket 42')
    })
})
