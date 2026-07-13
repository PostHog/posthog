import { ListVariable } from '../../types'
import { coerceListVariableValue, getListVariableValues } from './VariableFields'

const listVariable = (values: unknown): ListVariable =>
    ({
        id: '1',
        name: 'Schools',
        code_name: 'schools',
        type: 'List',
        values,
        default_value: '',
    }) as ListVariable

// `values`/`default_value`/`value` are JSONFields the API historically didn't validate, so
// API-created variables can hold non-string shapes. Rendering those uncoerced crashed
// dashboards with React error #31 (objects as children in LemonSelect labels).
describe('VariableFields list value coercion', () => {
    test.each([
        ['string passes through', 'abc', 'abc'],
        ['number is stringified', 42, '42'],
        ['boolean is stringified', true, 'true'],
        ['option object uses value over label', { label: 'School A', value: 5 }, '5'],
        ['option object falls back to label', { label: 'School A' }, 'School A'],
        ['option object with null value uses label', { label: 'School A', value: null }, 'School A'],
        ['object without scalar label/value is dropped', { label: { nested: true } }, null],
        ['array is dropped', [1, 2], null],
        ['null is dropped', null, null],
    ])('coerceListVariableValue: %s', (_name, input, expected) => {
        expect(coerceListVariableValue(input)).toEqual(expected)
    })

    test.each([
        ['non-array values', 'not-an-array', []],
        ['null values', null, []],
        ['string entries pass through unchanged', ['a', 'b'], ['a', 'b']],
        [
            'mixed entries are coerced and unusable ones dropped',
            [1, 'a', { label: 'School A', value: 5 }, { bad: 'shape' }, null],
            ['1', 'a', '5'],
        ],
    ])('getListVariableValues: %s', (_name, values, expected) => {
        expect(getListVariableValues(listVariable(values))).toEqual(expected)
    })
})
