import {
    assertRolloutFractions,
    buildIntegerMatcherWithPercentage,
    buildStableTeamMatcherWithPercentage,
} from './matchers'

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

    it('picks a fixed share of teams that a larger fraction keeps', () => {
        const teamIds = Array.from({ length: 10_000 }, (_, i) => i + 1)
        const picked = (config: string): number[] =>
            teamIds.filter((teamId) => buildStableTeamMatcherWithPercentage(config)(teamId))

        const onePercent = picked('*:0.01')
        const tenPercent = picked('*:0.1')

        expect(picked('*:0.01')).toEqual(onePercent)
        expect(onePercent.length).toBeGreaterThan(80)
        expect(onePercent.length).toBeLessThan(120)
        expect(tenPercent.length).toBeGreaterThan(900)
        expect(tenPercent.length).toBeLessThan(1100)
        expect(onePercent.every((teamId) => tenPercent.includes(teamId))).toBe(true)
    })
})
