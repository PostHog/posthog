import { lazyMap } from './lazyMap'

describe('lazyMap', () => {
    it('prepares and caches only cells read from a page of rows', () => {
        const format = jest.fn((value: number) => String(value))
        const source = Array.from({ length: 1000 }, (_, row) => [row, row + 1, row + 2])
        const rows = lazyMap(source, (row) => lazyMap(row, format))
        const page = rows.slice(100, 110)

        expect(format).not.toHaveBeenCalled()
        expect(page[0][2]).toBe('102')
        expect(rows[100][2]).toBe('102')
        expect(format).toHaveBeenCalledTimes(1)
        expect(page[9][0]).toBe('109')
        expect(format).toHaveBeenCalledTimes(2)
        expect(rows.length).toBe(1000)
        expect(page[0].length).toBe(3)
        expect(rows[1000]).toBeUndefined()
    })

    it('preserves array iteration, sorting, and writes without changing the source', () => {
        const source = [3, 1, 2]
        const rows = lazyMap(source, (value) => value * 2)

        expect(Array.isArray(rows)).toBe(true)
        expect(rows.map((value) => value + 1)).toEqual([7, 3, 5])
        expect([...rows]).toEqual([6, 2, 4])
        expect(rows.slice().sort((a, b) => a - b)).toEqual([2, 4, 6])
        rows[0] = 12
        expect(rows[0]).toBe(12)
        expect(source).toEqual([3, 1, 2])
        expect(lazyMap([], String)).toEqual([])
    })
})
