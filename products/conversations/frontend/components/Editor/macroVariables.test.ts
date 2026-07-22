import { JSONContent } from '@tiptap/core'

import { applyMacroVariables, applyMacroVariablesToRichContent } from './macroVariables'

describe('macroVariables', () => {
    it.each([
        ['Hi {{customer.name}}!', { 'customer.name': 'Ada' }, 'Hi Ada!'],
        ['Ticket #{{ ticket.number }}', { 'ticket.number': '42' }, 'Ticket #42'],
        // Unknown or unset tokens resolve to empty so no raw {{...}} reaches the customer.
        ['Hi {{customer.name}}', {}, 'Hi '],
        ['{{unknown.token}} done', { 'customer.name': 'Ada' }, ' done'],
    ])('applyMacroVariables(%j) fills known tokens and blanks the rest', (text, values, expected) => {
        expect(applyMacroVariables(text as string, values as Record<string, string>)).toBe(expected)
    })

    it('substitutes variables in every text node of a rich-content tree without mutating the input', () => {
        const input: JSONContent = {
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hey {{customer.name}}' }] }],
        }

        const result = applyMacroVariablesToRichContent(input, { 'customer.name': 'Ada' })

        expect(result.content?.[0].content?.[0].text).toBe('Hey Ada')
        // Original tree is untouched.
        expect(input.content?.[0].content?.[0].text).toBe('Hey {{customer.name}}')
    })
})
