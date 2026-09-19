import { movedRowsBand } from './metrics'

describe('movedRowsBand', () => {
    it.each([
        [0, '0'],
        [1, '1'],
        [2, '2-10'],
        [10, '2-10'],
        [11, '11-100'],
        [100, '11-100'],
        [101, '101-1000'],
        [1000, '101-1000'],
        [1001, '1001-10000'],
        [10000, '1001-10000'],
        [10001, '10001+'],
        [500000, '10001+'],
    ])('maps %i moved rows to band %s', (count, band) => {
        expect(movedRowsBand(count)).toBe(band)
    })
})
