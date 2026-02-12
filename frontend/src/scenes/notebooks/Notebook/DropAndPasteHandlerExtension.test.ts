import { detectTabularFormat, isTabularData, parseTabularDataToTipTapTable } from './DropAndPasteHandlerExtension'

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
    })
})
