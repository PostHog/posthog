import { TIB, formatBytes, formatCount, formatDuration, formatUsd } from './warehouseConsoleFormat'

describe('warehouseConsoleFormat', () => {
    it.each([
        [0, '0 B'],
        [4 * TIB, '4 TiB'],
        [5.534 * TIB, '5.53 TiB'],
        [1536, '1.5 KiB'],
    ])('formats %s bytes as %s', (bytes, expected) => {
        expect(formatBytes(bytes)).toBe(expected)
    })

    it.each([
        [676, '676 ms'],
        [7200, '7.2 s'],
        [10000, '10 s'],
        [125000, '2 m 05 s'],
        [3900000, '1 h 05 m'],
        [null, '-'],
    ])('formats %s ms as %s', (ms, expected) => {
        expect(formatDuration(ms)).toBe(expected)
    })

    it.each([
        ['0.004', '< $0.01'],
        ['0', '$0.00'],
        ['10.615', '$10.62'],
    ])('formats %s dollars as %s', (value, expected) => {
        expect(formatUsd(value)).toBe(expected)
    })

    it('adds thousands separators to counts', () => {
        expect(formatCount(3095)).toBe('3,095')
    })
})
