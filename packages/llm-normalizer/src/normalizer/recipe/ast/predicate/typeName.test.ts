import { matchesType, TypeName } from './typeName'

describe('matchesType', () => {
    it.each<[TypeName, unknown]>([
        ['string', 'hi'],
        ['number', 42],
        ['boolean', true],
        ['null', null],
        ['array', [1, 2]],
        ['object', { a: 1 }],
    ])('matches %s to its value', (type, value) => {
        expect(matchesType(value, type)).toBe(true)
    })

    it.each<[unknown]>([['hi'], [42], [null], [{ a: 1 }], [[1]]])('any matches everything (%p)', (value) => {
        expect(matchesType(value, 'any')).toBe(true)
    })

    it('object excludes arrays and null', () => {
        expect(matchesType([1, 2], 'object')).toBe(false)
        expect(matchesType(null, 'object')).toBe(false)
    })
})
