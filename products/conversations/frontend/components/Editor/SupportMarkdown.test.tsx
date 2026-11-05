import { render } from '@testing-library/react'

import { SupportMarkdown } from './SupportMarkdown'

// Jest replaces `react-markdown` with a stub that prints its source, so these cases assert the
// markdown handed to the renderer. The real renderer drops unescaped raw HTML (`skipHtml`).
describe('SupportMarkdown', () => {
    it.each([
        ['an unknown tag', 'Testing <example> here', 'Testing \\<example> here'],
        [
            'a pasted script snippet',
            '<script src="https://example.com/x.js"></script>',
            '\\<script src="https://example.com/x.js">\\</script>',
        ],
        ['a comparison with letters', 'if a<b and c>d', 'if a\\<b and c>d'],
        ['a tag in inline code', 'use `<example>` here', 'use `<example>` here'],
        ['a url autolink', 'see <https://example.com>', 'see <https://example.com>'],
    ])('sends %s to the markdown renderer in a form that shows it', (_, text, expected) => {
        const { container } = render(<SupportMarkdown>{text}</SupportMarkdown>)
        expect(container.textContent).toBe(expected)
    })
})
