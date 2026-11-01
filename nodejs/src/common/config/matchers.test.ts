import { assertRolloutFractions, buildIntegerMatcherWithPercentage } from './matchers'

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

    it.each([
        ['', false],
        ['*', false],
        ['123,*:0.01', false],
        ['*:1', false],
        ['*:10', true],
        ['*:1%', true],
        ['*:', true],
        ['*:0.01,*:5', true],
    ])('assertRolloutFractions(%s) throws: %s', (config, throws) => {
        const check = (): void => assertRolloutFractions('TEAMS', config)
        if (throws) {
            expect(check).toThrow("TEAMS takes a fraction between 0 and 1 after '*:'")
        } else {
            expect(check).not.toThrow()
        }
    })
})
