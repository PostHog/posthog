import { JSONContent } from '@tiptap/core'

import { expandFlattenedTablesInContent } from './expandFlattenedTablesInContent'

function paragraph(text: string): JSONContent {
    return { type: 'paragraph', content: [{ type: 'text', text }] }
}

describe('expandFlattenedTablesInContent', () => {
    it('rewrites a paragraph that contains a flattened table into a real table node', () => {
        const result = expandFlattenedTablesInContent([paragraph('| a | b | |---|---| | 1 | 2 |')])

        expect(result).toHaveLength(1)
        expect(result[0].type).toBe('table')
        expect(result[0].content).toHaveLength(2)
        expect(result[0].content?.[0].content?.[0].type).toBe('tableHeader')
        expect(result[0].content?.[1].content?.[1].content?.[0].content?.[0].text).toBe('2')
    })

    it('preserves surrounding nodes and only rewrites the flattened paragraph', () => {
        const heading: JSONContent = {
            type: 'heading',
            attrs: { level: 2 },
            content: [{ type: 'text', text: 'Title' }],
        }
        const trailing = paragraph('trailing paragraph')

        const result = expandFlattenedTablesInContent([heading, paragraph('| a | b | |---|---| | 1 | 2 |'), trailing])

        expect(result).toHaveLength(3)
        expect(result[0]).toBe(heading)
        expect(result[1].type).toBe('table')
        expect(result[2]).toBe(trailing)
    })

    it.each([
        { node: paragraph('plain prose with no table'), desc: 'plain prose' },
        { node: paragraph('see |foo| and |bar|'), desc: 'inline pipes without a delimiter row' },
        {
            node: { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: '# heading' }] },
            desc: 'non-paragraph node',
        },
        {
            node: {
                type: 'paragraph',
                content: [{ type: 'text', text: '| a | b | |---|---| | 1 | 2 |', marks: [{ type: 'bold' }] }],
            },
            desc: 'flattened table inside a marked text run',
        },
        {
            node: {
                type: 'paragraph',
                content: [
                    { type: 'text', text: '| a | b |' },
                    { type: 'hardBreak' },
                    { type: 'text', text: '|---|---|' },
                ],
            },
            desc: 'paragraph with mixed non-text children',
        },
    ])('leaves $desc untouched', ({ node }) => {
        expect(expandFlattenedTablesInContent([node])).toEqual([node])
    })
})
