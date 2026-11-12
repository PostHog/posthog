import type { Role } from '../environment/roles'
import type { RoleExit } from '../environment/supervisor'
import type { ValveTimelineEntry } from '../valves/valves'
import { Verdict, statusOf } from './status'

const HELD: Verdict = {
    minOffered: 0.9,
    units: { targetUnits: 60, offeredUnits: 60 },
    down: [],
    convergence: { converged: true, unfinishedJobs: 0, unrecorded: [], tookMs: 1000 },
    invariants: [{ name: 'at_least_once', passed: true, observed: 0, unitIds: [] }],
    timeline: [],
    exits: [],
}

const BROKEN = { name: 'at_least_once', passed: false, observed: 2, violation: 'run-1 email: lost', unitIds: ['run-1'] }

const EMAIL_WORKER = 'cdp-cyclotron-worker-email'
const HOGFLOW_WORKER = 'cdp-cyclotron-worker-hogflow'

const at = (second: number): string => new Date(Date.UTC(2026, 0, 5, 10, 0, second)).toISOString()

const killed = (role: string, applied: number, released?: number): ValveTimelineEntry => ({
    valve: 'role.kill',
    target: role,
    requestedAt: at(0),
    appliedAt: at(applied),
    observedAt: at(applied),
    releasedAt: released === undefined ? undefined : at(released),
})

const exited = (role: Role, second: number, byValve = false): RoleExit => ({
    role,
    at: at(second),
    code: null,
    signal: 'SIGKILL',
    byValve,
})

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
            'a role was killed by its valve and every invariant held',
            { timeline: [killed(EMAIL_WORKER, 10, 11)], exits: [exited(EMAIL_WORKER, 10, true)] },
            'passed',
            'every invariant held',
        ],
        [
            'a role exited without a valve causing it',
            { exits: [exited(HOGFLOW_WORKER, 20)] },
            'failed',
            `${HOGFLOW_WORKER} exited (SIGKILL) without a valve causing it`,
        ],
        [
            'a role exited while a valve on it was applied',
            {
                timeline: [{ ...killed(HOGFLOW_WORKER, 10, 30), valve: 'role.freeze' }],
                exits: [exited(HOGFLOW_WORKER, 20)],
            },
            'failed',
            `${HOGFLOW_WORKER} exited (SIGKILL) without a valve causing it, while role.freeze on ${HOGFLOW_WORKER} was applied`,
        ],
        [
            "a role exited while the roles' Postgres connections were dropped",
            {
                timeline: [{ ...killed('postgres', 10, 30), valve: 'pg.drop_connections' }],
                exits: [{ ...exited(HOGFLOW_WORKER, 20), signal: null, code: 1 }],
            },
            'failed',
            `${HOGFLOW_WORKER} exited (code 1) without a valve causing it, while pg.drop_connections on postgres was applied`,
        ],
        [
            'a role exited after a valve on another role was released',
            { timeline: [killed(EMAIL_WORKER, 10, 11)], exits: [exited(HOGFLOW_WORKER, 20)] },
            'failed',
            `${HOGFLOW_WORKER} exited (SIGKILL) without a valve causing it`,
        ],
        [
            'a role exited while a valve on another role was applied',
            { timeline: [killed(EMAIL_WORKER, 10, 30)], exits: [exited(HOGFLOW_WORKER, 20)] },
            'failed',
            `${HOGFLOW_WORKER} exited (SIGKILL) without a valve causing it`,
        ],
        [
            'a valve was never observed',
            {
                timeline: [{ valve: 'role.kill', target: EMAIL_WORKER, requestedAt: at(0), error: 'never applied' }],
                invariants: [BROKEN],
            },
            'invalid',
            `role.kill on ${EMAIL_WORKER} was not observed: never applied`,
        ],
        [
            'a role crashed on its own, so the valve on it found nothing running',
            {
                timeline: [
                    {
                        valve: 'role.kill',
                        target: EMAIL_WORKER,
                        requestedAt: at(0),
                        error: `${EMAIL_WORKER} is not running`,
                    },
                ],
                exits: [exited(EMAIL_WORKER, 20)],
            },
            'failed',
            `${EMAIL_WORKER} exited (SIGKILL) without a valve causing it; role.kill on ${EMAIL_WORKER} was not observed: ${EMAIL_WORKER} is not running`,
        ],
        [
            'another role crashed while a valve was never observed',
            {
                timeline: [{ valve: 'role.kill', target: EMAIL_WORKER, requestedAt: at(0), error: 'never applied' }],
                exits: [exited(HOGFLOW_WORKER, 20)],
            },
            'failed',
            `${HOGFLOW_WORKER} exited (SIGKILL) without a valve causing it; role.kill on ${EMAIL_WORKER} was not observed: never applied`,
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
