import { usableId } from './usableId'

describe('usableId', () => {
    it.each([
        ['a real id', '4BF92F3577B34DA6A3CE929D0E0E4736', '4bf92f3577b34da6a3ce929d0e0e4736'],
        ['an all-zero trace id', '0'.repeat(32), null],
        ['an all-zero span id', '0'.repeat(16), null],
        ['a missing id', null, null],
        ['an empty id', '', null],
        ['a value with path characters', 'a/b', null],
        ['a value that is not hex', 'notatrace', null],
        ['an odd-length hex value', 'abc', null],
    ])('resolves %s', (_name, value, expected) => {
        expect(usableId(value)).toBe(expected)
    })
})
