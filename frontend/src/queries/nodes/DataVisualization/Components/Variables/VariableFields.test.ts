import { ListVariable } from '../../types'
import { coerceListVariableValue, getListVariableValues } from './VariableFields'

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
})
