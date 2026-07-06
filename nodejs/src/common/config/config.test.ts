import { buildIntegerMatcherWithPercentage } from './config'

describe('buildIntegerMatcherWithPercentage', () => {
    it.each([
        ['', 123, false],
        [undefined, 123, false],
        ['*', 123, true],
        ['*', 456, true],
        ['123,456', 123, true],
        ['123,456', 456, true],
        ['123,456', 789, false],
        ['*:1.0', 123, true],
        ['*:0', 123, false],
        ['123,*:0', 123, true],
        ['123,*:0', 456, false],
    ])('buildIntegerMatcherWithPercentage(%s)(%s) === %s', (config, id, expected) => {
        expect(buildIntegerMatcherWithPercentage(config as string | undefined)(id as number)).toBe(expected)
    })
})
