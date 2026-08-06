import { expandFlattenedMarkdownTables, stripMarkdown } from 'lib/utils/markdown'

describe('markdown utils', () => {
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

    describe('expandFlattenedMarkdownTables', () => {
        it('expands a flattened table into separate rows', () => {
            const input = '| a | b | |---|---| | 1 | 2 |'
            expect(expandFlattenedMarkdownTables(input)).toBe(['| a | b |', '|---|---|', '| 1 | 2 |'].join('\n'))
        })

        it('expands a flattened table embedded between other markdown lines', () => {
            const input = ['# Heading', '| a | b | |---|---| | 1 | 2 |', 'trailing paragraph'].join('\n')
            expect(expandFlattenedMarkdownTables(input)).toBe(
                ['# Heading', '| a | b |', '|---|---|', '| 1 | 2 |', 'trailing paragraph'].join('\n')
            )
        })

        it('expands a flattened table whose rows are glued together with no whitespace', () => {
            const input =
                '| Month | Boost | Scale ||-------|-------|-------|| Jul 2025 | 54 | 20 || Aug 2025 | 59 | 26 |'
            expect(expandFlattenedMarkdownTables(input)).toBe(
                [
                    '| Month | Boost | Scale |',
                    '|-------|-------|-------|',
                    '| Jul 2025 | 54 | 20 |',
                    '| Aug 2025 | 59 | 26 |',
                ].join('\n')
            )
        })

        it('handles alignment markers in the delimiter row', () => {
            const input = '| a | b | c | | :--- | :---: | ---: | | 1 | 2 | 3 |'
            expect(expandFlattenedMarkdownTables(input)).toBe(
                ['| a | b | c |', '| :--- | :---: | ---: |', '| 1 | 2 | 3 |'].join('\n')
            )
        })

        it('expands a header + delimiter row table with no data rows', () => {
            const input = '| a | b | |---|---|'
            expect(expandFlattenedMarkdownTables(input)).toBe(['| a | b |', '|---|---|'].join('\n'))
        })

        it('leaves a well-formed multi-line table untouched', () => {
            const input = ['| a | b |', '|---|---|', '| 1 | 2 |'].join('\n')
            expect(expandFlattenedMarkdownTables(input)).toBe(input)
        })

        it.each([
            { input: 'just a plain paragraph of text', desc: 'plain prose' },
            { input: 'see |foo| and |bar| for details', desc: 'inline pipes without a delimiter row' },
            { input: '| a | | b |', desc: 'two glued segments without a delimiter row' },
            { input: '', desc: 'empty string' },
            { input: '# Heading\n\nplain paragraph', desc: 'markdown without any pipes' },
        ])('leaves $desc untouched', ({ input }) => {
            expect(expandFlattenedMarkdownTables(input)).toBe(input)
        })
    })
})
