import { stripMarkdown } from './stripMarkdown'

describe('stripMarkdown', () => {
    it.each([
        // Basic text
        ['plain text', 'plain text'],

        // Unordered lists with dashes
        ['- item 1\n- item 2\n- item 3', '- item 1\n- item 2\n- item 3'],

        // Ordered lists with numbers
        ['1. first\n2. second\n3. third', '1. first\n2. second\n3. third'],

        // Ordered list starting at different number
        ['5. fifth\n6. sixth', '5. fifth\n6. sixth'],

        // Links with URL preserved
        ['[click here](https://example.com)', 'click here (https://example.com)'],
        ['[PostHog](https://posthog.com/docs)', 'PostHog (https://posthog.com/docs)'],

        // Link without text
        ['[](https://example.com)', 'https://example.com'],

        // Relative links get prefixed with origin
        ['[docs](/docs/guide)', `docs (${window.location.origin}/docs/guide)`],
        ['[api](api/v1)', `api (${window.location.origin}/api/v1)`],

        // Bold/italic/code stripped
        ['**bold** and *italic*', 'bold and italic'],
        ['`inline code`', 'inline code'],

        // Headings stripped
        ['# Heading 1', 'Heading 1'],
        ['## Heading 2', 'Heading 2'],

        // Mixed content
        [
            '# Title\n\n- item 1\n- item 2\n\n[link](https://test.com)',
            'Title\n\n- item 1\n- item 2\n\nlink (https://test.com)',
        ],
    ])('converts %j to %j', (input, expected) => {
        expect(stripMarkdown(input)).toBe(expected)
    })
})
