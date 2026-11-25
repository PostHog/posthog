import { readFileSync } from 'fs'
import path from 'path'
import { parse, stringify } from 'yaml'

import { PROFILES_DIR, load, loadText } from '../cards'
import type { InvariantResult } from '../judge/judge'
import type { ValveTimelineEntry } from '../valves/valves'
import { FaultedRun, JudgedRun, controlOf, pairOf, pairProblemsOf } from './pair'
import type { RunVerdict } from './runner'

const CARDS = path.join(__dirname, '..', 'cards')
const VALVED = load(path.join(CARDS, 'destination-errors.yaml'))
const CARD = {
    ...VALVED,
    card: {
        ...VALVED.card,
        invariants: [...VALVED.card.invariants, { name: 'no_loss', params: {} }],
        gates: { ...VALVED.card.gates, no_loss: 0 },
    },
}
const DRIVE = { startedAt: 1_000, endedAt: 61_000 }

const held: InvariantResult = { name: 'no_loss', passed: true, observed: 0, unitIds: [] }
const lost: InvariantResult = {
    name: 'no_loss',
    passed: false,
    observed: 2,
    violation: 'run-1 webhook to hooks.example.com: accepted 0 times by the recovery horizon, expected 1',
    unitIds: ['run-1'],
}

const observed = (valve: number): ValveTimelineEntry => ({
    valve: 'dest.status',
    target: 'hooks.example.com',
    requestedAt: new Date(DRIVE.startedAt).toISOString(),
    intentAt: new Date(DRIVE.startedAt + 5_000 + valve * 21_000).toISOString(),
    observedAt: new Date(DRIVE.startedAt + 5_100 + valve * 21_000).toISOString(),
    releasedAt: new Date(DRIVE.startedAt + 15_000 + valve * 21_000).toISOString(),
})

const FAULTS = [observed(0), observed(1), observed(2)]

const run = (runId: string, verdict: Partial<RunVerdict> = {}): JudgedRun => ({
    verdict: {
        runId,
        status: 'passed',
        statusReason: 'every invariant held',
        cardId: CARD.card.id,
        cardHash: CARD.cardHash,
        profileHash: CARD.profileHash,
        origin: 'local-agent',
        target: 'local',
        convergence: { converged: true, unfinishedJobs: 0, unrecorded: [], tookMs: 4_500 },
        invariants: [held],
        measurements: [],
        admissions: [],
        bars: [],
        timeline: [],
        startedAt: '2026-01-01T00:00:00.000Z',
        endedAt: '2026-01-01T00:02:00.000Z',
        evidenceDir: `/tmp/${runId}`,
        ...verdict,
    },
    queue: [],
    drive: DRIVE,
    units: { targetUnits: 100, offeredUnits: 100 },
})

const CLEAN = run('control')
const BREACHED = run('faulted', {
    status: 'failed',
    statusReason: `no_loss failed: ${lost.violation}`,
    invariants: [lost],
    timeline: FAULTS,
})

describe('pairOf', () => {
    it.each<[string, JudgedRun, FaultedRun, string, RegExp]>([
        [
            'a clean control and a breached faulted run',
            CLEAN,
            BREACHED,
            'fault',
            /^the control held no_loss at the same seed and offered load, and the faulted run did not: run-1 webhook/,
        ],
        [
            'a control that failed',
            run('control', { status: 'failed', statusReason: `no_loss failed: ${lost.violation}`, invariants: [lost] }),
            BREACHED,
            'open',
            /^the control failed at the same seed and offered load, so the faulted run's result is not attributed to the fault: no_loss failed/,
        ],
        [
            'a control that judged no no_loss',
            run('control', { invariants: [] }),
            BREACHED,
            'unjudged',
            /^the control run judged no no_loss$/,
        ],
        [
            'a control whose no_loss was not judged',
            run('control', {
                status: 'invalid',
                invariants: [{ ...held, passed: false, unjudged: 'the truth skips from seq 4 to 6' }],
            }),
            BREACHED,
            'unjudged',
            /^the control run's no_loss was not judged: the truth skips from seq 4 to 6$/,
        ],
        [
            'an invalid control',
            run('control', { status: 'invalid', statusReason: 'the run was interrupted' }),
            BREACHED,
            'unjudged',
            /^the control run is invalid: the run was interrupted$/,
        ],
        [
            'a faulted run that did not run',
            CLEAN,
            { missing: 'the reset before run control failed' },
            'unjudged',
            /^the faulted run did not run: the reset before run control failed$/,
        ],
        [
            'a faulted run whose fault was not observed',
            CLEAN,
            run('faulted', {
                status: 'invalid',
                invariants: [lost],
                timeline: [
                    ...FAULTS.slice(0, 2),
                    { ...FAULTS[2], observedAt: undefined, error: 'applied but not observed' },
                ],
            }),
            'unjudged',
            /^the fault evidence is missing: dest\.status on hooks\.example\.com was not observed: applied but not observed$/,
        ],
        [
            'a faulted run that applied no fault',
            CLEAN,
            run('faulted', { invariants: [lost], status: 'failed' }),
            'unjudged',
            /^the faulted run applied no fault$/,
        ],
        [
            'a control whose evidence could not be written',
            { ...CLEAN, evidenceError: 'journal.json: disk full' },
            BREACHED,
            'unjudged',
            /^the control run is invalid: every invariant held; the evidence could not be written: journal\.json: disk full$/,
        ],
        [
            'a faulted run whose evidence could not be written',
            CLEAN,
            { ...BREACHED, evidenceError: 'journal.json: disk full' },
            'unjudged',
            /^the faulted run is invalid: no_loss failed: .*; the evidence could not be written: journal\.json: disk full$/,
        ],
        [
            'a control that offered fewer units than the faulted run',
            { ...CLEAN, units: { targetUnits: 100, offeredUnits: 92 } },
            BREACHED,
            'unjudged',
            /^the control offered 92 of its 100 units, so it may not have carried the faulted run's load$/,
        ],
        [
            'a control that offered as many units as the faulted run, but not all it targeted',
            { ...CLEAN, units: { targetUnits: 100, offeredUnits: 92 } },
            { ...BREACHED, units: { targetUnits: 100, offeredUnits: 92 } },
            'unjudged',
            /^the control offered 92 of its 100 units, so it may not have carried the faulted run's load$/,
        ],
        [
            'a faulted run that held no_loss',
            CLEAN,
            run('faulted', { timeline: FAULTS }),
            'none',
            /^the control and the faulted run both held no_loss$/,
        ],
    ])('attributes %s', (_story, control, faulted, attribution, reason) => {
        expect(pairOf(CARD, control, faulted)).toMatchObject({ attribution, reason: expect.stringMatching(reason) })
    })

    it("records each run's admission, queue growth, drain, fault dose and no_loss result", () => {
        const admissions = [
            { name: 'load' as const, passed: true, reason: 'every baseline rate within 20% of its target' },
        ]
        const control = { ...run('control', { admissions }), queue: [] }
        const faulted = {
            ...BREACHED,
            queue: [
                { at: DRIVE.startedAt - 5_000, due: 90, running: 0, oldestDueSeconds: 30, inserted: 0 },
                { at: DRIVE.startedAt + 1_000, due: 3, running: 1, oldestDueSeconds: 1, inserted: 10 },
                { at: DRIVE.startedAt + 6_000, error: 'the probe timed out' },
                { at: DRIVE.startedAt + 11_000, due: 41, running: 4, oldestDueSeconds: 12, inserted: 80 },
                { at: DRIVE.startedAt + 16_000, due: 7, running: 2, oldestDueSeconds: 2, inserted: 120 },
                { at: DRIVE.endedAt + 5_000, due: 400, running: 0, oldestDueSeconds: 90, inserted: 120 },
            ],
        }

        expect(pairOf(CARD, control, faulted)).toEqual({
            attribution: 'fault',
            reason: expect.any(String),
            controlRunId: 'control',
            faultedRunId: 'faulted',
            runs: [
                {
                    role: 'control',
                    runId: 'control',
                    status: 'passed',
                    statusReason: 'every invariant held',
                    admissions,
                    offered: { targetUnits: 100, offeredUnits: 100 },
                    queue: null,
                    drainSeconds: 4.5,
                    faultDose: [],
                    noLoss: { passed: true, observed: 0, violation: null, unjudged: null },
                },
                {
                    role: 'faulted',
                    runId: 'faulted',
                    status: 'failed',
                    statusReason: BREACHED.verdict.statusReason,
                    admissions: [],
                    offered: { targetUnits: 100, offeredUnits: 100 },
                    queue: { dueAtStart: 3, peakDue: 41, growth: 38, peakOldestDueSeconds: 12 },
                    drainSeconds: 4.5,
                    faultDose: CARD.card.valves.map(({ valve, target, dose }, i) => ({
                        valve,
                        target,
                        dose,
                        observedAt: FAULTS[i].observedAt,
                        releasedAt: FAULTS[i].releasedAt,
                        error: null,
                    })),
                    noLoss: { passed: false, observed: 2, violation: lost.violation, unjudged: null },
                },
            ],
        })
    })

    it('hashes the control as the card it runs: the same card with its valves removed', () => {
        const yaml = parse(readFileSync(path.join(CARDS, 'destination-errors.yaml'), 'utf8'))
        const valveFree = loadText('valve-free', {
            card: stringify({
                ...yaml,
                valves: [],
                invariants: [...yaml.invariants, { name: 'no_loss' }],
                gates: { ...yaml.gates, no_loss: 0 },
            }),
            profile: readFileSync(path.join(PROFILES_DIR, `${yaml.profile}.yaml`), 'utf8'),
        })

        expect(controlOf(CARD)).toEqual(valveFree)
    })

    it('drops from the control only the checks that need a fault', () => {
        const bounces = load(path.join(CARDS, 'ses-bounce-suppresses.yaml'))

        expect(controlOf(bounces).card.invariants.map(({ name }) => name)).toEqual(
            bounces.card.invariants.map(({ name }) => name).filter((name) => name !== 'bounced_suppressed')
        )
    })
})

describe('pairProblemsOf', () => {
    it.each<[string, typeof CARD, RegExp | undefined]>([
        ['a card with valves that judges no_loss', CARD, undefined],
        [
            'a card without valves',
            { ...CARD, card: { ...CARD.card, valves: [] } },
            /needs a card that applies valves and judges no_loss/,
        ],
        [
            'a card with a valve that runs only on a run host',
            {
                ...CARD,
                card: {
                    ...CARD.card,
                    valves: [{ valve: 'pg.failover', target: 'cyclotron', dose: {}, at: '5s', for: '10s' }],
                },
            },
            /pg\.failover runs only on a run host/,
        ],
    ])('takes or refuses %s', (_story, loaded, refusal) => {
        expect(pairProblemsOf(loaded)).toEqual(refusal === undefined ? [] : [expect.stringMatching(refusal)])
    })
})
