import { buildIntegerMatcherWithPercentage } from './matchers'

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
        ['123,*', 456, true],
        ['123:1', 123, true],
        ['123:1', 456, false],
        ['123:0', 123, false],
        ['123:0,*', 123, false],
        ['123:0,*', 456, true],
        [' 123 : 1 , * : 0 ', 123, true],
    ])('buildIntegerMatcherWithPercentage(%s)(%s) === %s', (config, id, expected) => {
        expect(buildIntegerMatcherWithPercentage(config as string | undefined)(id as number)).toBe(expected)
    })

    it.each<[string, number, number, boolean]>([
        // A per-team fraction draws for each call, as the '*' fraction does.
        ['123:0.5', 123, 0.49, true],
        ['123:0.5', 123, 0.5, false],
        ['123:0.5', 456, 0, false],
        // The team's own fraction wins over the '*' fraction, in both directions.
        ['123:0.5,*:0.1', 123, 0.3, true],
        ['123:0.5,*:0.1', 456, 0.3, false],
        ['123:0.5,*:0.1', 456, 0.05, true],
        ['123:0.1,*:0.5', 123, 0.3, false],
    ])('buildIntegerMatcherWithPercentage(%j)(%s) with Math.random() = %s === %s', (config, id, draw, expected) => {
        jest.spyOn(Math, 'random').mockReturnValue(draw)
        expect(buildIntegerMatcherWithPercentage(config)(id)).toBe(expected)
    })

    it.each([
        ['*:10', /takes a fraction between 0 and 1/],
        ['123:1.5', /takes a fraction between 0 and 1/],
        ['123:-0.1', /takes a fraction between 0 and 1/],
        ['123:0.5x', /takes a fraction between 0 and 1/],
        ['123:', /takes a fraction between 0 and 1/],
        ['abc', /is not a team id/],
        ['12.5', /is not a team id/],
        ['-1', /is not a team id/],
        ['123,,456', /is not a team id/],
        ['123,123:0.5', /team 123 appears more than once/],
        ['*:0.1,*', /'\*' appears more than once/],
    ])('buildIntegerMatcherWithPercentage(%j) throws %s', (config, error) => {
        expect(() => buildIntegerMatcherWithPercentage(config)).toThrow(error)
    })
})
