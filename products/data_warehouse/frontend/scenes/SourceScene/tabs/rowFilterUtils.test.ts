import { RowFilter } from '~/types'

import { isMultiValueOperator, parseInList, validateInListValue, validateRowFilters } from './rowFilterUtils'

describe('rowFilterUtils', () => {
    describe('isMultiValueOperator', () => {
        it('is true only for IN / NOT IN', () => {
            expect(isMultiValueOperator('IN')).toBe(true)
            expect(isMultiValueOperator('NOT IN')).toBe(true)
            expect(isMultiValueOperator('=')).toBe(false)
            expect(isMultiValueOperator('>')).toBe(false)
        })
    })

    describe('parseInList', () => {
        it.each([
            ['1,2,3', ['1', '2', '3']],
            ['1, 2, 3', ['1', '2', '3']],
            ['  1 , 2 ,3 ', ['1', '2', '3']],
            ["'abc','cde'", ['abc', 'cde']],
            ["'abc', 'cde'", ['abc', 'cde']],
            ["'a,b','c'", ['a,b', 'c']],
            ["'o''brien'", ["o'brien"]],
            ['', []],
        ])('parses %p', (raw, expected) => {
            expect(parseInList(raw)).toEqual(expected)
        })

        it('throws on an unterminated quote', () => {
            expect(() => parseInList("'abc")).toThrow()
        })
    })

    describe('validateInListValue', () => {
        it('accepts a valid integer list', () => {
            expect(validateInListValue('integer', '1, 2, 3')).toBeNull()
        })

        it('accepts a valid string list', () => {
            expect(validateInListValue('string', "'a','b'")).toBeNull()
        })

        it('rejects an empty list', () => {
            expect(validateInListValue('integer', '')).toBe('Enter at least one value')
        })

        it('rejects a blank element', () => {
            expect(validateInListValue('integer', '1,,2')).toBe('The list has an empty value')
        })

        it('rejects a non-integer element', () => {
            expect(validateInListValue('integer', '1, abc, 3')).toContain('not a whole number')
        })

        it('rejects an unterminated quote', () => {
            expect(validateInListValue('string', "'abc")).toBe('Unterminated quote in list')
        })

        it('validates boolean elements as true/false', () => {
            expect(validateInListValue('boolean', 'true, false')).toBeNull()
            expect(validateInListValue('boolean', 'yes, no')).toContain('must be true or false')
        })
    })

    describe('validateRowFilters with IN operators', () => {
        const context = { availableColumns: [{ name: 'id', data_type: 'integer' }] }

        it('passes a valid IN filter', () => {
            const filters: RowFilter[] = [{ column: 'id', operator: 'IN', value: '1, 2, 3' }]
            expect(validateRowFilters(filters, context)).toEqual({})
        })

        it('flags an invalid IN element', () => {
            const filters: RowFilter[] = [{ column: 'id', operator: 'NOT IN', value: '1, x' }]
            expect(Object.keys(validateRowFilters(filters, context))).toEqual(['0'])
        })
    })
})
