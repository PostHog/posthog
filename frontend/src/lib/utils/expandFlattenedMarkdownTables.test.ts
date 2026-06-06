import { expandFlattenedMarkdownTables } from './expandFlattenedMarkdownTables'

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
