import { ListVariable } from '../../types'
import { coerceListVariableValue, getListVariableValues } from './VariableFields'
import {
    formatRelativeDateValue,
    getListVariableSelectedValues,
    isRelativeDateValue,
    normalizeRelativeDateAmount,
    parseRelativeDateValue,
} from './variableUtils'

const listVariable = (values: unknown): ListVariable =>
    ({
        id: '1',
        name: 'Test',
        code_name: 'test',
        type: 'List',
        values,
        default_value: '',
    }) as ListVariable

describe('VariableFields', () => {
    // `values` is a JSONField, so API-created variables can hold non-string entries.
    // Rendering those directly crashes React (error #31), so everything must coerce
    // to a string.
    test.each([
        ['strings pass through', ['a', 'b'], ['a', 'b']],
        ['numbers become strings', [1, 2.5], ['1', '2.5']],
        ['booleans become strings', [true, false], ['true', 'false']],
        ['option-shaped objects use their value', [{ label: 'School 1', value: '1' }], ['1']],
        ['label-only objects use their label', [{ label: 'School 2' }], ['School 2']],
        ['unrecognized objects become JSON', [{ foo: 'bar' }], ['{"foo":"bar"}']],
        ['null entries are dropped', [null, 'a', undefined], ['a']],
        ['non-array values become an empty list', 'not-an-array', []],
    ])('getListVariableValues: %s', (_name, values, expected) => {
        expect(getListVariableValues(listVariable(values))).toEqual(expected)
    })

    test.each([
        ['null stays null', null, null],
        ['scalar becomes string', 5, '5'],
        ['array becomes JSON', [1, 2, 3], '[1,2,3]'],
    ])('coerceListVariableValue: %s', (_name, value, expected) => {
        expect(coerceListVariableValue(value)).toBe(expected)
    })

    test.each([
        ['single value stays scalar-shaped', false, ['first', 'second'], ['first']],
        ['multiple values are preserved', true, ['first', 'second'], ['first', 'second']],
        ['a scalar default becomes one selected value', true, 'first', ['first']],
        ['an empty default has no selected values', true, '', []],
    ])('getListVariableSelectedValues: %s', (_name, isMulti, defaultValue, expected) => {
        expect(
            getListVariableSelectedValues({
                ...listVariable(['first', 'second']),
                is_multi: isMulti,
                default_value: defaultValue,
            })
        ).toEqual(expected)
    })

    test.each([
        ['a rolling offset', '-30d', true, { amount: 30, unit: 'd' }, '30 days ago'],
        ['the current time', '-0h', true, { amount: 0, unit: 'h' }, 'Now'],
        ['a fixed date', '2026-08-06', false, null, '2026-08-06'],
        ['a unit only the backend resolves', '-1q', false, null, '-1q'],
        ['a period boundary only the backend resolves', 'mStart', false, null, 'mStart'],
    ])('relative date helpers: %s', (_name, value, isRelative, parsed, formatted) => {
        expect(isRelativeDateValue(value)).toBe(isRelative)
        expect(parseRelativeDateValue(value)).toEqual(parsed)
        expect(formatRelativeDateValue(value)).toBe(formatted)
    })

    test.each([
        ['whole number', 30, 30],
        ['fractional number', 1.5, 2],
        ['negative number', -5, 0],
        ['empty number input', Number.NaN, 0],
    ])('normalizeRelativeDateAmount: %s', (_name, amount, expected) => {
        expect(normalizeRelativeDateAmount(amount)).toBe(expected)
    })
})
