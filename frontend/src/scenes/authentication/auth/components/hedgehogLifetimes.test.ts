import { hedgehogLifetimes } from './hedgehogLifetimes'

describe('hedgehogLifetimes', () => {
    it.each([
        [0, 'Less than 0.01 hedgehog lifetimes'],
        [60, 'Less than 0.01 hedgehog lifetimes'],
        [94672800, '1 hedgehog lifetime'],
        [189345600, '2 hedgehog lifetimes'],
        [94672800000000, '1 million hedgehog lifetimes'],
    ])('formats %s seconds as %s', (seconds, expected) => {
        expect(hedgehogLifetimes(seconds)).toBe(expected)
    })
})
