import type { Profile } from '../cards/schema'
import type { Role } from '../environment/roles'
import type { RoleExit } from '../environment/supervisor'
import type { Baseline } from '../judge/measurements'
import type { WriterSample } from '../probe/writer-probe'
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
    writer: [],
    drive: { startedAt: Date.UTC(2026, 0, 5, 10, 0, 0), endedAt: Date.UTC(2026, 0, 5, 10, 0, 50) },
    bars: [],
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

const failedOver: ValveTimelineEntry = {
    valve: 'pg.failover',
    target: 'cyclotron',
    requestedAt: at(0),
    intentAt: at(10),
    appliedAt: at(10),
    observedAt: at(12),
    releaseIntentAt: at(30),
    releasedAt: at(32),
}

const dropped = (from: number, to: number): ValveTimelineEntry => ({
    valve: 'pg.drop_connections',
    target: 'postgres',
    requestedAt: at(0),
    intentAt: at(from),
    appliedAt: at(from),
    observedAt: at(from),
    releasedAt: at(to),
})

const probed = (failing: (second: number) => string | false): WriterSample[] =>
    Array.from({ length: 56 }, (_, second) => {
        const failure = failing(second)
        const sample = { at: Date.parse(at(second)), monoMs: second * 1000, latencyMs: 5 }
        return failure === false
            ? { ...sample, ok: true }
            : { ...sample, ok: false, ...(failure === 'timeout' ? {} : { sqlstate: failure }) }
    })

const exited = (role: Role, second: number, byValve = false, replica = 0): RoleExit => ({
    role,
    replica,
    at: at(second),
    code: null,
    signal: 'SIGKILL',
    byValve,
})

const exitedWithError = (role: Role, second: number): RoleExit => ({ ...exited(role, second), code: 1, signal: null })

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
            'a second replica exited while its role was killed on replica 0',
            {
                timeline: [killed(EMAIL_WORKER, 10, 11)],
                exits: [exited(EMAIL_WORKER, 10, true), exited(EMAIL_WORKER, 10, false, 1)],
            },
            'failed',
            `${EMAIL_WORKER}-1 exited (SIGKILL) without a valve causing it`,
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
            'a bar broke at a ramp step while every invariant held',
            {
                bars: [
                    {
                        name: 'pickup_p99_under',
                        unit: 's',
                        limit: 5,
                        passed: false,
                        breakingPoint: {
                            scale: 10,
                            at: at(30),
                            offeredPerSecond: 12.34,
                            key: 'hogflow',
                            value: 10,
                            part: 'role:cdp-cyclotron-worker-hogflow',
                        },
                    },
                ],
            },
            'failed',
            'pickup_p99_under broke at the 10x step, 12.3 units/s offered: hogflow 10 s',
        ],
        [
            'a bar could not be judged',
            {
                bars: [
                    {
                        name: 'writer_cpu_under',
                        unit: '%',
                        limit: 70,
                        passed: false,
                        unjudged: 'no writer CPU reading off a run host in the 1x step',
                    },
                ],
            },
            'invalid',
            'writer_cpu_under was not judged: no writer CPU reading off a run host in the 1x step',
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
            'pg.failover could not fail back',
            {
                timeline: [{ ...failedOver, releaseError: 'the fail-back request was refused: InternalFailure' }],
                invariants: [BROKEN],
            },
            'invalid',
            'pg.failover on cyclotron did not fail back: the fail-back request was refused: InternalFailure',
        ],
        [
            'the writer probe failed five times in a row before the failover',
            {
                timeline: [failedOver],
                writer: probed((second) => (second >= 3 && second <= 7 ? 'timeout' : false)),
                invariants: [BROKEN],
            },
            'invalid',
            `Cyclotron interrupted without a valve: 5 writer probes failed in a row before any valve applied, at ${at(7)}`,
        ],
        [
            'the writer probe lost its connection once after the drive and the fail-back',
            { timeline: [failedOver], writer: probed((second) => (second === 52 ? '08006' : false)) },
            'invalid',
            `Cyclotron interrupted without a valve: a writer probe lost its connection (SQLSTATE 08006) after the drive and every valve ended, at ${at(52)}`,
        ],
        [
            'a card without a valve whose writer probe lost its connection across the drive end',
            {
                writer: [{ at: Date.parse(at(49)), monoMs: 49_000, ok: false, latencyMs: 2000, sqlstate: '57P01' }],
            },
            'invalid',
            `Cyclotron interrupted without a valve: a writer probe lost its connection (SQLSTATE 57P01) with no valve applied, at ${at(49)}`,
        ],
        [
            'the writer probe timed out once before the failover and lost its connection during it',
            {
                timeline: [failedOver],
                writer: probed((second) => (second === 3 ? 'timeout' : second >= 10 && second <= 20 ? '57P01' : false)),
            },
            'passed',
            'every invariant held',
        ],
        [
            'a role exited during the failover',
            { timeline: [failedOver], exits: [exited(HOGFLOW_WORKER, 15)] },
            'failed',
            `${HOGFLOW_WORKER} exited (SIGKILL) without a valve causing it, while pg.failover on cyclotron was applied`,
        ],
        [
            "a role exited with an error while the roles' Postgres connections were dropped",
            { timeline: [dropped(10, 40)], exits: [exitedWithError(HOGFLOW_WORKER, 25)] },
            'passed',
            'every invariant held',
        ],
        [
            'a role exited with an error just after the connection drop released',
            { timeline: [dropped(10, 40)], exits: [exitedWithError(HOGFLOW_WORKER, 44)] },
            'passed',
            'every invariant held',
        ],
        [
            'a role exited with an error well after the connection drop released',
            { timeline: [dropped(10, 40)], exits: [exitedWithError(HOGFLOW_WORKER, 46)] },
            'failed',
            `${HOGFLOW_WORKER} exited (code 1) without a valve causing it`,
        ],
        [
            'a role exited with an error before the connection drop applied',
            { timeline: [dropped(10, 40)], exits: [exitedWithError(HOGFLOW_WORKER, 8)] },
            'failed',
            `${HOGFLOW_WORKER} exited (code 1) without a valve causing it`,
        ],
        [
            'a role exited with an error after the connection drop failed to apply',
            {
                timeline: [
                    {
                        valve: 'pg.drop_connections',
                        target: 'postgres',
                        requestedAt: at(0),
                        intentAt: at(10),
                        error: 'the first sweep failed',
                    },
                ],
                exits: [exitedWithError(HOGFLOW_WORKER, 25)],
            },
            'failed',
            `${HOGFLOW_WORKER} exited (code 1) without a valve causing it; pg.drop_connections on postgres was not observed: the first sweep failed`,
        ],
        [
            'a role exited with an error during a valve that sets no exit grace',
            { timeline: [failedOver], exits: [exitedWithError(HOGFLOW_WORKER, 15)] },
            'failed',
            `${HOGFLOW_WORKER} exited (code 1) without a valve causing it, while pg.failover on cyclotron was applied`,
        ],
        [
            'a role failed to start while the connections were dropped',
            {
                timeline: [dropped(10, 40)],
                exits: [{ ...exited(HOGFLOW_WORKER, 25), signal: null, error: 'spawn ENOENT' }],
            },
            'failed',
            `${HOGFLOW_WORKER} exited (code null) without a valve causing it, while pg.drop_connections on postgres was applied`,
        ],
        [
            'a role was killed by a signal while the connections were dropped',
            { timeline: [dropped(10, 40)], exits: [exited(HOGFLOW_WORKER, 25)] },
            'failed',
            `${HOGFLOW_WORKER} exited (SIGKILL) without a valve causing it, while pg.drop_connections on postgres was applied`,
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
