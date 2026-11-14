import type { Profile } from '../cards/schema'
import type { Role } from '../environment/roles'
import type { RoleExit } from '../environment/supervisor'
import type { Baseline } from '../judge/measurements'
import type { ValveTimelineEntry } from '../valves/valves'
import { Admission, Verdict, admissionsOf, statusOf } from './status'

const HELD: Verdict = {
    admissions: [],
    minOffered: 0.9,
    units: { targetUnits: 60, offeredUnits: 60 },
    down: [],
    convergence: { converged: true, unfinishedJobs: 0, unrecorded: [], tookMs: 1000 },
    invariants: [{ name: 'at_least_once', passed: true, observed: 0, unitIds: [] }],
    timeline: [],
    exits: [],
}

const REFUSED_LOAD: Admission = { name: 'load', passed: false, reason: 'email claims 1/s, not within 10% of 4/s' }

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

const exited = (role: Role, second: number, byValve = false, replica = 0): RoleExit => ({
    role,
    replica,
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
            'a second replica exited while its role was killed on replica 0',
            {
                timeline: [killed(EMAIL_WORKER, 10, 11)],
                exits: [exited(EMAIL_WORKER, 10, true), exited(EMAIL_WORKER, 10, false, 1)],
            },
            'failed',
            `${EMAIL_WORKER}-1 exited (SIGKILL) without a valve causing it, while role.kill on ${EMAIL_WORKER} was applied`,
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
            { timeline: [{ valve: 'role.kill', target: EMAIL_WORKER, requestedAt: at(0), error: 'never applied' }] },
            'invalid',
            `role.kill on ${EMAIL_WORKER} was not observed: never applied`,
        ],
        [
            'an invariant failed while a valve was never observed',
            {
                timeline: [{ valve: 'role.kill', target: EMAIL_WORKER, requestedAt: at(0), error: 'never applied' }],
                invariants: [BROKEN],
            },
            'failed',
            `role.kill on ${EMAIL_WORKER} was not observed: never applied; at_least_once failed: run-1 email: lost`,
        ],
        [
            'a valve was observed but not released',
            {
                timeline: [
                    { ...killed(EMAIL_WORKER, 10), valve: 'ses.throttle', target: 'ses', error: 'edge answered 500' },
                ],
                invariants: [BROKEN],
            },
            'invalid',
            'ses.throttle on ses was not released: edge answered 500',
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
            'the baseline load missed its target',
            {
                admissions: [REFUSED_LOAD, { name: 'host', passed: false, reason: 'host CPU 95% busy' }],
                invariants: [BROKEN],
            },
            'invalid',
            'the load admission failed: email claims 1/s, not within 10% of 4/s; the host admission failed: host CPU 95% busy',
        ],
        [
            'every admission passed',
            { admissions: [{ name: 'load', passed: true, reason: 'every baseline rate within 10% of its target' }] },
            'passed',
            'every invariant held',
        ],
        [
            'a dependency went away',
            { down: ['provider-edge'], invariants: [BROKEN], admissions: [REFUSED_LOAD] },
            'invalid',
            'dependencies went away: provider-edge',
        ],
    ])('%s', (_story, change, status, statusReason) => {
        expect(statusOf({ ...HELD, ...change })).toEqual({ status, statusReason })
    })

    const BASELINE: Baseline = {
        seconds: 600,
        scrapedSeconds: 600,
        claimsPerSecond: { email: 3.8, hogflow: 2 },
        newJobsPerSecond: 5.5,
        hostBusyShare: 0.62,
    }
    const LOAD: Profile['load'] = { targets: { claimsPerSecond: { email: 4 }, newJobsPerSecond: 5 }, tolerance: 0.1 }

    it.each<[string, Pick<Profile, 'load' | 'host'>, Partial<Baseline>, Admission[]]>([
        ['admits nothing for a profile that sets neither', {}, {}, []],
        [
            'admits a baseline within the tolerance of every target',
            { load: LOAD },
            {},
            [{ name: 'load', passed: true, reason: 'every baseline rate within 10% of its target' }],
        ],
        [
            'refuses a baseline that missed a queue and the new jobs',
            { load: { ...LOAD, targets: { claimsPerSecond: { email: 4, hogflow: 3 }, newJobsPerSecond: 5 } } },
            { newJobsPerSecond: 6 },
            [
                {
                    name: 'load',
                    passed: false,
                    reason: 'hogflow claims 2/s, not within 10% of 3/s, new jobs 6/s, not within 10% of 5/s',
                },
            ],
        ],
        [
            'refuses claim targets when the role metrics covered too little of the baseline',
            { load: LOAD },
            { scrapedSeconds: 10, claimsPerSecond: {} },
            [
                {
                    name: 'load',
                    passed: false,
                    reason: 'the role metrics covered 10s of the baseline, under the 30s minimum',
                },
            ],
        ],
        [
            'refuses a run whose valve came before any baseline',
            { load: LOAD },
            { seconds: 0 },
            [{ name: 'load', passed: false, reason: 'the drive had no baseline before its valve' }],
        ],
        [
            'refuses both admissions when the baseline was too short to measure',
            { load: LOAD, host: { cpuCeiling: 0.7 } },
            { seconds: 4.2 },
            [
                {
                    name: 'load',
                    passed: false,
                    reason: 'the baseline was too short to measure: 4.2s, under the 30s minimum',
                },
                {
                    name: 'host',
                    passed: false,
                    reason: 'the baseline was too short to measure: 4.2s, under the 30s minimum',
                },
            ],
        ],
        [
            'admits a host under its CPU ceiling',
            { host: { cpuCeiling: 0.7 } },
            {},
            [{ name: 'host', passed: true, reason: 'host CPU 62% busy in the baseline, under the 70% ceiling' }],
        ],
        [
            'refuses a host at its CPU ceiling',
            { host: { cpuCeiling: 0.62 } },
            {},
            [{ name: 'host', passed: false, reason: 'host CPU 62% busy in the baseline, over the 62% ceiling' }],
        ],
        [
            'refuses a host without CPU samples',
            { host: { cpuCeiling: 0.7 } },
            { hostBusyShare: undefined },
            [{ name: 'host', passed: false, reason: 'no host CPU sample covers the baseline' }],
        ],
    ])('%s', (_story, profile, baseline, admissions) => {
        expect(admissionsOf(profile, { ...BASELINE, ...baseline })).toEqual(admissions)
    })
})
