import { checkCapturedCode, sourceFileWindow } from './sourceFileWindow'

const FILE = Array.from({ length: 10 }, (_, i) => `line ${i + 1}`)

describe('sourceFileWindow', () => {
    test.each([
        { name: 'middle of the file', line: 5, above: 2, below: 2, expected: [3, 7], moreAbove: true, moreBelow: true },
        {
            name: 'clamped at the start',
            line: 2,
            above: 5,
            below: 1,
            expected: [1, 3],
            moreAbove: false,
            moreBelow: true,
        },
        {
            name: 'clamped at the end',
            line: 10,
            above: 1,
            below: 5,
            expected: [9, 10],
            moreAbove: true,
            moreBelow: false,
        },
    ])('windows the $name', ({ line, above, below, expected, moreAbove, moreBelow }) => {
        const window = sourceFileWindow(FILE, line, above, below)!
        const numbers = [...window.context.before, window.context.line, ...window.context.after].map((l) => l.number)

        expect([numbers[0], numbers[numbers.length - 1]]).toEqual(expected)
        expect(window.context.line).toEqual({ number: line, line: `line ${line}` })
        expect([window.hasMoreAbove, window.hasMoreBelow]).toEqual([moreAbove, moreBelow])
    })

    test.each([null, 0, 11])('has no window for line %s', (line) => {
        expect(sourceFileWindow(FILE, line, 5, 5)).toBeNull()
    })
})

describe('checkCapturedCode', () => {
    test.each([
        { name: 'same code', captured: '  line 4 ', expected: 'matches' },
        { name: 'other code', captured: 'return 1', expected: 'differs' },
        { name: 'no captured code', captured: null, expected: 'unchecked' },
        { name: 'captured code cut at 300 characters', captured: 'lin...✂️', expected: 'matches' },
    ])('reports $name as $expected', ({ captured, expected }) => {
        expect(checkCapturedCode(FILE, 4, captured)).toBe(expected)
    })
})
