import { Verdict, statusOf } from './status'

const HELD: Verdict = {
    minOffered: 0.9,
    units: { targetUnits: 60, offeredUnits: 60 },
    down: [],
    convergence: { converged: true, unfinishedJobs: 0, unrecorded: [], tookMs: 1000 },
    invariants: [{ name: 'at_least_once', passed: true, observed: 0, unitIds: [] }],
}

const BROKEN = { name: 'at_least_once', passed: false, observed: 2, violation: 'run-1 email: lost', unitIds: ['run-1'] }

describe('statusOf', () => {
    it.each<[string, Partial<Verdict>, string, string]>([
        ['every invariant held', {}, 'passed', 'every invariant held'],
        ['an invariant failed', { invariants: [BROKEN] }, 'failed', 'at_least_once failed: run-1 email: lost'],
        [
            'the stack did not converge',
            { convergence: { converged: false, unfinishedJobs: 4, unrecorded: ['run-1', 'run-2'], tookMs: 120000 } },
            'failed',
            'not converged: 4 unfinished jobs, 2 units without a delivery record',
        ],
        [
            'the generator offered under minOffered',
            { units: { targetUnits: 60, offeredUnits: 53 }, invariants: [BROKEN] },
            'invalid',
            'the generator offered 53 of 60 units, under minOffered 0.9',
        ],
        [
            'a dependency went away',
            { down: ['provider-edge'], invariants: [BROKEN] },
            'invalid',
            'dependencies went away: provider-edge',
        ],
    ])('%s', (_story, change, status, statusReason) => {
        expect(statusOf({ ...HELD, ...change })).toEqual({ status, statusReason })
    })
})
