import { formatEstimateCount, hedgehogLifetimes } from './hedgehogLifetimes'

describe('hedgehogLifetimes', () => {
    it.each([
        [6, '6'],
        [1056170, '1.06 million'],
        [1e12, 'over 1 trillion'],
        [1e60, 'over 1 trillion'],
    ])('bounds the remaining count %s as %s', (count, expected) => {
        expect(formatEstimateCount(count)).toBe(expected)
    })

    it.each([
        [0, 'Less than 0.01 hedgehog lifetimes'],
        [60, 'Less than 0.01 hedgehog lifetimes'],
        [94672800, '1 hedgehog lifetime'],
        [189345600, '2 hedgehog lifetimes'],
        [94672800000000, '1 million hedgehog lifetimes'],
        [1e68, 'over 1 trillion hedgehog lifetimes'],
    ])('formats %s seconds as %s', (seconds, expected) => {
        expect(hedgehogLifetimes(seconds)).toBe(expected)
    })
})
