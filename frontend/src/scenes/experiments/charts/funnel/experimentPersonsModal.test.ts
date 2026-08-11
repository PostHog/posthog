import { experimentActorsFunnelStep } from './experimentPersonsModal'

describe('experimentActorsFunnelStep', () => {
    it.each([
        ['exposure step conversions are not queryable', 0, true, null],
        ['exposure step drop-offs are not queryable', 0, false, null],
        ['first metric step conversions map to step 1', 1, true, 1],
        ['first metric step drop-offs are not queryable', 1, false, null],
        ['second metric step conversions map to step 2', 2, true, 2],
        ['second metric step drop-offs map to step -2', 2, false, -2],
        ['third metric step drop-offs map to step -3', 3, false, -3],
    ])('%s', (_name, stepIndex, converted, expected) => {
        expect(experimentActorsFunnelStep(stepIndex as number, converted as boolean)).toBe(expected)
    })
})
