import { buildInputAssignmentCode, parseInputOptions } from './NotebookNodeInputV2'

describe('NotebookNodeInputV2 assignment building', () => {
    // The assignment executes in the kernel: a malformed literal or an unvalidated variable
    // name would let widget input break out of the assignment statement.
    test.each([
        ['text value is a quoted literal', 'date_from', 'text', '2026-07-01', 'date_from = "2026-07-01"'],
        ['quotes and newlines stay inside the literal', 'label', 'text', 'a"b\nc', 'label = "a\\"b\\nc"'],
        ['number passes through numerically', 'limit', 'number', '50', 'limit = 50'],
        ['non-numeric number input is rejected', 'limit', 'number', 'abc', null],
        ['blank number input is rejected', 'limit', 'number', '  ', null],
        ['invalid variable name is rejected', 'not a name', 'text', 'x', null],
        ['expression-shaped variable is rejected', 'x; import os', 'text', 'x', null],
    ] as const)('%s', (_name, variable, widgetType, value, expected) => {
        expect(buildInputAssignmentCode(variable, widgetType, value)).toEqual(expected)
    })

    it('parses select options from commas and newlines, dropping blanks', () => {
        expect(parseInputOptions('a, b\nc,\n , d')).toEqual(['a', 'b', 'c', 'd'])
    })
})
