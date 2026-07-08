import { JSONContent } from '@tiptap/core'

import { convertMarkdownTablesInContent } from './convertMarkdownTablesInContent'

function paragraph(text: string): JSONContent {
    return { type: 'paragraph', content: [{ type: 'text', text }] }
}

describe('convertMarkdownTablesInContent', () => {
    it('rewrites a paragraph that contains a flattened table into a real table node', () => {
        const result = convertMarkdownTablesInContent([paragraph('| a | b | |---|---| | 1 | 2 |')])

        expect(result).toHaveLength(1)
        expect(result[0].type).toBe('table')
        expect(result[0].content).toHaveLength(2)
        expect(result[0].content?.[0].content?.[0].type).toBe('tableHeader')
        expect(result[0].content?.[1].content?.[1].content?.[0].content?.[0].text).toBe('2')
    })

    it('rewrites consecutive paragraphs that form a multi-line markdown table', () => {
        const result = convertMarkdownTablesInContent([
            paragraph('| Period | Boost % | Scale % |'),
            paragraph('|--------|---------|---------|'),
            paragraph('| Jul 2025 | ~71% | ~29% |'),
            paragraph('| Aug 2025 | 70% | 30% |'),
        ])

        expect(result).toHaveLength(1)
        expect(result[0].type).toBe('table')
        // header row + 2 data rows
        expect(result[0].content).toHaveLength(3)
        expect(result[0].content?.[0].content?.[0].type).toBe('tableHeader')
        expect(result[0].content?.[0].content?.[0].content?.[0].content?.[0].text).toBe('Period')
        expect(result[0].content?.[2].content?.[2].content?.[0].content?.[0].text).toBe('30%')
    })

    it('preserves surrounding nodes and only rewrites the table run', () => {
        const heading: JSONContent = {
            type: 'heading',
            attrs: { level: 2 },
            content: [{ type: 'text', text: 'Title' }],
        }
        const trailing = paragraph('trailing paragraph')

        const result = convertMarkdownTablesInContent([
            heading,
            paragraph('| a | b |'),
            paragraph('|---|---|'),
            paragraph('| 1 | 2 |'),
            trailing,
        ])

        expect(result).toHaveLength(3)
        expect(result[0]).toBe(heading)
        expect(result[1].type).toBe('table')
        expect(result[2]).toBe(trailing)
    })

    it('preserves surrounding nodes around a flattened single-line table', () => {
        const heading: JSONContent = {
            type: 'heading',
            attrs: { level: 2 },
            content: [{ type: 'text', text: 'Title' }],
        }
        const trailing = paragraph('trailing paragraph')

        const result = convertMarkdownTablesInContent([heading, paragraph('| a | b | |---|---| | 1 | 2 |'), trailing])

        expect(result).toHaveLength(3)
        expect(result[0]).toBe(heading)
        expect(result[1].type).toBe('table')
        expect(result[2]).toBe(trailing)
    })

    it('converts two separate tables split by a non-table paragraph', () => {
        const result = convertMarkdownTablesInContent([
            paragraph('| a | b |'),
            paragraph('|---|---|'),
            paragraph('| 1 | 2 |'),
            paragraph('some prose in between'),
            paragraph('| c | d |'),
            paragraph('|---|---|'),
            paragraph('| 3 | 4 |'),
        ])

        expect(result).toHaveLength(3)
        expect(result[0].type).toBe('table')
        expect(result[1]).toEqual(paragraph('some prose in between'))
        expect(result[2].type).toBe('table')
    })

    it.each([
        { nodes: [paragraph('plain prose with no table')], desc: 'plain prose' },
        { nodes: [paragraph('see |foo| and |bar|')], desc: 'inline pipes without a delimiter row' },
        { nodes: [paragraph('| a | b |')], desc: 'a lone table row with no delimiter' },
        {
            nodes: [paragraph('| a | b |'), paragraph('| 1 | 2 |')],
            desc: 'consecutive pipe rows with no delimiter',
        },
        {
            nodes: [{ type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: '# heading' }] }],
            desc: 'non-paragraph node',
        },
        {
            nodes: [
                {
                    type: 'paragraph',
                    content: [{ type: 'text', text: '| a | b | |---|---| | 1 | 2 |', marks: [{ type: 'bold' }] }],
                },
            ],
            desc: 'flattened table inside a marked text run',
        },
        {
            nodes: [
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: '| a | b |' },
                        { type: 'hardBreak' },
                        { type: 'text', text: '|---|---|' },
                    ],
                },
            ],
            desc: 'paragraph with mixed non-text children',
        },
    ])('leaves $desc untouched', ({ nodes }) => {
        expect(convertMarkdownTablesInContent(nodes)).toEqual(nodes)
    })
})
