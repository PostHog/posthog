import { parseMarkdownToTipTap } from 'lib/utils/parseMarkdownToTipTap'

import {
    detectMarkdown,
    detectTabularFormat,
    isTabularData,
    parseMarkdownPasteContent,
    parseTabularDataToTipTapTable,
} from './DropAndPasteHandlerExtension'

describe('DropAndPasteHandlerExtension', () => {
    describe('detectTabularFormat', () => {
        it.each([
            { input: 'A\tB\n1\t2', expected: 'tsv', desc: 'two rows with tabs' },
            { input: 'A\tB\tC\n1\t2\t3\n4\t5\t6', expected: 'tsv', desc: 'three rows with tabs' },
            { input: 'A,B\n1,2', expected: 'csv', desc: 'two rows with commas' },
            { input: 'A,B,C\n1,2,3\n4,5,6', expected: 'csv', desc: 'three rows with commas' },
            { input: 'hello\tworld', expected: null, desc: 'single line with tab' },
            { input: 'hello,world', expected: null, desc: 'single line with comma' },
            { input: 'just plain text', expected: null, desc: 'plain text' },
            { input: '', expected: null, desc: 'empty string' },
            { input: 'line1\nline2', expected: null, desc: 'multi-line without delimiters' },
            { input: 'A,B\nno commas here', expected: null, desc: 'inconsistent comma counts' },
        ])('returns $expected for $desc', ({ input, expected }) => {
            expect(detectTabularFormat(input)).toBe(expected)
        })
    })

    describe('isTabularData', () => {
        it.each([
            { input: 'A\tB\n1\t2', expected: true, desc: 'TSV data' },
            { input: 'A,B\n1,2', expected: true, desc: 'CSV data' },
            { input: 'A\tB\n1\t2\n', expected: true, desc: 'trailing newline' },
            { input: 'A\tB\n1\t2\n\n\n', expected: true, desc: 'multiple trailing newlines' },
            { input: 'hello\tworld', expected: false, desc: 'single line with tab' },
            { input: 'just plain text', expected: false, desc: 'plain text no tabs' },
            { input: '', expected: false, desc: 'empty string' },
            { input: 'line1\nline2', expected: false, desc: 'multi-line without tabs' },
            { input: 'A\tB\nno tabs here', expected: false, desc: 'mixed lines with and without tabs' },
        ])('returns $expected for $desc', ({ input, expected }) => {
            expect(isTabularData(input)).toBe(expected)
        })
    })

    describe('parseTabularDataToTipTapTable', () => {
        it('parses a 2x2 table with first row as headers', () => {
            const result = parseTabularDataToTipTapTable('Name\tAge\nAlice\t30')

            expect(result.type).toBe('table')
            expect(result.content).toHaveLength(2)

            // Header row
            const headerRow = result.content![0]
            expect(headerRow.type).toBe('tableRow')
            expect(headerRow.content).toHaveLength(2)
            expect(headerRow.content![0].type).toBe('tableHeader')
            expect(headerRow.content![0].content![0].content![0].text).toBe('Name')
            expect(headerRow.content![1].content![0].content![0].text).toBe('Age')

            // Data row
            const dataRow = result.content![1]
            expect(dataRow.content![0].type).toBe('tableCell')
            expect(dataRow.content![0].content![0].content![0].text).toBe('Alice')
            expect(dataRow.content![1].content![0].content![0].text).toBe('30')
        })

        it('handles empty cells', () => {
            const result = parseTabularDataToTipTapTable('A\tB\n\t2')

            const dataRow = result.content![1]
            expect(dataRow.content![0].content![0].content).toEqual([])
            expect(dataRow.content![1].content![0].content![0].text).toBe('2')
        })

        it('trims whitespace from cell values', () => {
            const result = parseTabularDataToTipTapTable('  A  \t  B  \n 1 \t 2 ')

            const headerRow = result.content![0]
            expect(headerRow.content![0].content![0].content![0].text).toBe('A')
            expect(headerRow.content![1].content![0].content![0].text).toBe('B')
        })

        it('normalizes ragged rows by padding with empty cells', () => {
            const result = parseTabularDataToTipTapTable('A\tB\tC\n1\t2')

            const dataRow = result.content![1]
            expect(dataRow.content).toHaveLength(3)
            expect(dataRow.content![2].content![0].content).toEqual([])
        })

        it('strips trailing newlines before parsing', () => {
            const result = parseTabularDataToTipTapTable('A\tB\n1\t2\n\n')

            expect(result.content).toHaveLength(2)
        })

        it('handles a 3x3 table', () => {
            const result = parseTabularDataToTipTapTable('H1\tH2\tH3\nA\tB\tC\nD\tE\tF')

            expect(result.content).toHaveLength(3)
            expect(result.content![0].content).toHaveLength(3)
            expect(result.content![2].content![2].content![0].content![0].text).toBe('F')
        })

        it('parses CSV with comma delimiter', () => {
            const result = parseTabularDataToTipTapTable('Name,Age\nAlice,30', ',')

            expect(result.type).toBe('table')
            expect(result.content).toHaveLength(2)

            const headerRow = result.content![0]
            expect(headerRow.content![0].content![0].content![0].text).toBe('Name')
            expect(headerRow.content![1].content![0].content![0].text).toBe('Age')

            const dataRow = result.content![1]
            expect(dataRow.content![0].content![0].content![0].text).toBe('Alice')
            expect(dataRow.content![1].content![0].content![0].text).toBe('30')
        })

        it('strips quotes from CSV quoted fields', () => {
            const result = parseTabularDataToTipTapTable('"df","df"\n"123","456"', ',')

            const headerRow = result.content![0]
            expect(headerRow.content![0].content![0].content![0].text).toBe('df')
            expect(headerRow.content![1].content![0].content![0].text).toBe('df')

            const dataRow = result.content![1]
            expect(dataRow.content![0].content![0].content![0].text).toBe('123')
            expect(dataRow.content![1].content![0].content![0].text).toBe('456')
        })

        it('handles commas inside quoted CSV fields', () => {
            const result = parseTabularDataToTipTapTable('"Name","Note"\n"Alice","hello, world"', ',')

            const dataRow = result.content![1]
            expect(dataRow.content![0].content![0].content![0].text).toBe('Alice')
            expect(dataRow.content![1].content![0].content![0].text).toBe('hello, world')
        })
    })

    describe('detectMarkdown', () => {
        it.each([
            { input: '# Heading', expected: true, desc: 'ATX h1' },
            { input: '### Heading three', expected: true, desc: 'ATX h3' },
            { input: '- item one\n- item two', expected: true, desc: 'unordered list' },
            { input: '* item one\n* item two', expected: true, desc: 'asterisk list' },
            { input: '1. first\n2. second', expected: true, desc: 'ordered list' },
            { input: '> quoted line', expected: true, desc: 'blockquote' },
            { input: '```ts\nconst a = 1\n```', expected: true, desc: 'fenced code block' },
            { input: 'before\n\n---\n\nafter', expected: true, desc: 'horizontal rule' },
            { input: '| a | b |\n| - | - |\n| 1 | 2 |', expected: true, desc: 'markdown table' },
            { input: 'just a plain paragraph of text', expected: false, desc: 'plain paragraph' },
            { input: 'some *inline* emphasis only', expected: false, desc: 'inline emphasis only' },
            { input: '', expected: false, desc: 'empty string' },
            { input: '#nospace', expected: false, desc: 'hash without space (not a heading)' },
        ])('returns $expected for $desc', ({ input, expected }) => {
            expect(detectMarkdown(input)).toBe(expected)
        })

        it('detects markdown in the example pasted by the user', () => {
            const markdown = [
                '# Phase 6: Tool migration and deprecation',
                '',
                '## Purpose',
                '',
                'Decide which existing analytics paths can move to PostHog.',
                '',
                '- Every existing tool path has a decision.',
                '- Migration decisions are backed by evidence.',
            ].join('\n')
            expect(detectMarkdown(markdown)).toBe(true)
        })
    })

    describe('parseMarkdownToTipTap', () => {
        it('returns an empty array for empty input', () => {
            expect(parseMarkdownToTipTap('')).toEqual([])
            expect(parseMarkdownToTipTap('   \n  ')).toEqual([])
        })

        it('parses headings into heading nodes', () => {
            const result = parseMarkdownToTipTap('# Title\n\n## Subtitle')

            expect(result[0].type).toBe('heading')
            expect(result[0].attrs?.level).toBe(1)
            expect(result[0].content?.[0].text).toBe('Title')
            expect(result[1].type).toBe('heading')
            expect(result[1].attrs?.level).toBe(2)
            expect(result[1].content?.[0].text).toBe('Subtitle')
        })

        it('parses unordered lists into bulletList nodes', () => {
            const result = parseMarkdownToTipTap('- one\n- two')

            expect(result[0].type).toBe('bulletList')
            expect(result[0].content).toHaveLength(2)
            expect(result[0].content?.[0].type).toBe('listItem')
        })

        it('parses ordered lists into orderedList nodes', () => {
            const result = parseMarkdownToTipTap('1. first\n2. second')

            expect(result[0].type).toBe('orderedList')
            expect(result[0].content).toHaveLength(2)
        })

        it('parses inline bold into a strong mark', () => {
            const result = parseMarkdownToTipTap('This is **bold** text.')

            const paragraph = result[0]
            expect(paragraph.type).toBe('paragraph')
            const boldNode = paragraph.content?.find((node) => node.marks?.some((mark) => mark.type === 'bold'))
            expect(boldNode?.text).toBe('bold')
        })

        it('parses fenced code blocks', () => {
            const result = parseMarkdownToTipTap('```\nconst x = 1\n```')

            expect(result[0].type).toBe('codeBlock')
            expect(result[0].content?.[0].text).toBe('const x = 1')
        })

        it('parses a flattened table whose rows were joined on a single line', () => {
            const result = parseMarkdownToTipTap('| a | b | |---|---| | 1 | 2 | | 3 | 4 |')

            expect(result[0].type).toBe('table')
            expect(result[0].content).toHaveLength(3)
            const headerRow = result[0].content?.[0]
            expect(headerRow?.content?.[0].type).toBe('tableHeader')
            expect(headerRow?.content?.[0].content?.[0].content?.[0].text).toBe('a')
            const lastRow = result[0].content?.[2]
            expect(lastRow?.content?.[1].content?.[0].content?.[0].text).toBe('4')
        })

        it('parses an AI-formatted flattened table whose rows are glued with no whitespace', () => {
            const result = parseMarkdownToTipTap('| Month | Boost ||-------|-------|| Jul 2025 | 54 || Aug 2025 | 59 |')

            expect(result[0].type).toBe('table')
            expect(result[0].content).toHaveLength(3)
            const headerRow = result[0].content?.[0]
            expect(headerRow?.content?.[0].type).toBe('tableHeader')
            expect(headerRow?.content?.[0].content?.[0].content?.[0].text).toBe('Month')
            const lastRow = result[0].content?.[2]
            expect(lastRow?.content?.[0].content?.[0].content?.[0].text).toBe('Aug 2025')
            expect(lastRow?.content?.[1].content?.[0].content?.[0].text).toBe('59')
        })
    })

    describe('parseMarkdownPasteContent', () => {
        // A flattened markdown table glued with no whitespace, as AI responses / rendered docs
        // put it on the clipboard. The matching HTML carries it as plain pipe-text, not a
        // real <table>, so without the table exception it would be lost on paste.
        const FLATTENED_TABLE =
            '| Month | Boost | Scale | Teams | Total ||-------|-------|-------|-------|-------|| Jul 2025 | 54 | 20 | — | 74 || Aug 2025 | 59 | 26 | — | 85 |'

        it('parses a flattened table even when an HTML representation is present', () => {
            const result = parseMarkdownPasteContent(FLATTENED_TABLE, '<meta charset="utf-8"><span>| Month |...</span>')

            expect(result).not.toBeNull()
            expect(result![0].type).toBe('table')
            expect(result![0].content).toHaveLength(3)
        })

        it('parses a flattened table when there is no HTML representation', () => {
            const result = parseMarkdownPasteContent(FLATTENED_TABLE, undefined)

            expect(result).not.toBeNull()
            expect(result![0].type).toBe('table')
        })

        it('defers to the default paste for non-table markdown when HTML is present', () => {
            expect(parseMarkdownPasteContent('# Title\n\n- one\n- two', '<h1>Title</h1>')).toBeNull()
        })

        it('parses non-table markdown when there is no HTML representation', () => {
            const result = parseMarkdownPasteContent('# Title', undefined)

            expect(result).not.toBeNull()
            expect(result![0].type).toBe('heading')
        })

        it('returns null for plain text that is not markdown', () => {
            expect(parseMarkdownPasteContent('just some plain text', undefined)).toBeNull()
            expect(parseMarkdownPasteContent('', undefined)).toBeNull()
        })
    })
})
