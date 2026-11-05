import { render } from '@testing-library/react'

import { unsafeMarkup, XSS_PAYLOADS } from 'lib/components/AgentObjectTags/xssTestUtils'

import { SupportMarkdown } from './SupportMarkdown'

// Jest replaces `react-markdown` with a stub that prints its source, so these cases assert the
// markdown handed to the renderer. The real renderer drops unescaped raw HTML (`skipHtml`).
describe('SupportMarkdown', () => {
    it.each([
        ['an unknown tag', 'Testing <example> here', 'Testing &lt;example> here'],
        [
            'a pasted script snippet',
            '<script src="https://example.com/x.js"></script>',
            '&lt;script src="https&#58;//example.com/x.js">&lt;/script>',
        ],
        ['a comparison with letters', 'if a<b and c>d', 'if a&lt;b and c>d'],
        ['a tag in inline code', 'use `<example>` here', 'use `<example>` here'],
        ['a url autolink', 'see <https://example.com>', 'see <https://example.com>'],
    ])('sends %s to the markdown renderer in a form that shows it', (_, text, expected) => {
        const { container } = render(<SupportMarkdown>{text}</SupportMarkdown>)
        expect(container.textContent).toBe(expected)
    })

    it.each(XSS_PAYLOADS)('hands the markdown renderer no raw markup from %s', (_, payload) => {
        const { container } = render(<SupportMarkdown>{`before ${payload} after`}</SupportMarkdown>)
        expect(unsafeMarkup(container.textContent ?? '')).toEqual([])
    })
})
