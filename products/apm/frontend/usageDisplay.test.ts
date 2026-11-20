import { formatBytes, formatShare } from './usageDisplay'

describe('usageDisplay', () => {
    test.each([
        [0, '0 B'],
        [999, '999 B'],
        [1_000, '1.0 kB'],
        [1_500_000, '1.5 MB'],
        // Billing counts gigabytes in powers of 1000, so 2^30 bytes is 1.07 GB here, not 1 GB.
        [1_073_741_824, '1.07 GB'],
        [2_500_000_000_000, '2.50 TB'],
    ])('formats %d bytes as %s', (bytes, expected) => {
        expect(formatBytes(bytes)).toBe(expected)
    })

    test.each([
        [0, 0, null],
        [5, 0, null],
        [1, 3, '33%'],
        [1, 1000, '0.1%'],
        [1, 100000, '<0.1%'],
    ])('formats %d of %d as %s', (value, total, expected) => {
        expect(formatShare(value, total)).toBe(expected)
    })
})
