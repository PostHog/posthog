import { SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'
import { mkdtempSync, rmSync } from 'fs'
import os from 'os'
import path from 'path'

import { EmailTrackingCodeSigner } from '~/cdp/services/messaging/helpers/tracking-code'
import { internalFetch } from '~/common/utils/request'

import type { ResidentBacklog } from '../backlog/backlog'
import type { Backlog } from '../cards'
import { ProviderEdge, TruthRecord, UNIT_EMAIL_DOMAIN, startProviderEdge } from '../provider-edge'
import { atLeastOnce } from './invariants'
import { FollowUpAnswer, JournalEntry, Judge, RunEvidence, createJudge } from './judge'
import { edgeTruth } from './truth'

const TRACKING_KEYS = 'scenario-tracking-key'
const UNIT = 'run-a-1'
const NO_RESETS: RunEvidence = { janitorResets: 0, unobserved: [] }
const SEED = { teamIds: [7] }
const NEVER_ABORTED = new AbortController().signal
const NOBODY_LISTENING = 'http://127.0.0.1:1/public/m/ses_webhook'

describe('judge', () => {
    let edge: ProviderEdge
    let ses: SESv2Client
    let unfinishedJobs: number
    let clockMs: number
    let probeTakesMs: number
    let resident: ResidentBacklog | undefined
    let truthFails: string | undefined
    let truthLoses: number | undefined
    let duringProbe: (() => Promise<unknown>) | undefined
    let polls: number
    let probeAnswers: number
    let judge: Judge
    let caDir: string

    beforeAll(() => {
        caDir = mkdtempSync(path.join(os.tmpdir(), 'judge-edge-'))
    })

    afterAll(() => {
        rmSync(caDir, { recursive: true, force: true })
    })

    const judgeOf = (): Judge =>
        createJudge({
            truth: {
                head: (read) => edgeTruth(edge.url).head(read),
                after: (cursor, read) => {
                    if (truthFails === undefined) {
                        return edgeTruth(edge.url)
                            .after(cursor, read)
                            .then((page) => ({
                                ...page,
                                records: page.records.filter(({ seq }) => seq !== truthLoses),
                            }))
                    }
                    clockMs += probeTakesMs
                    return Promise.reject(new Error(truthFails))
                },
            },
            probe: {
                unfinishedJobs: async () => {
                    clockMs += probeTakesMs
                    polls += 1
                    await duringProbe?.()
                    return polls > probeAnswers
                        ? Promise.reject(new Error('The operation was aborted due to timeout'))
                        : Promise.resolve(unfinishedJobs)
                },
            },
            fetchRetries: 3,
            residentBacklog: () => Promise.resolve(resident!),
            pollMs: 10,
            now: () => clockMs,
        })

    beforeEach(async () => {
        edge = await startProviderEdge({
            port: 0,
            trackingKeys: TRACKING_KEYS,
            caDir,
            feedbackUrl: NOBODY_LISTENING,
        })
        ses = new SESv2Client({
            endpoint: edge.url,
            region: 'us-east-1',
            credentials: { accessKeyId: 'edge', secretAccessKey: 'edge' },
            maxAttempts: 1,
        })
        unfinishedJobs = 0
        clockMs = 0
        probeTakesMs = 10
        resident = undefined
        truthFails = undefined
        truthLoses = undefined
        duringProbe = undefined
        polls = 0
        probeAnswers = Infinity
        judge = judgeOf()
        await judge.open(SEED)
    })

    afterEach(async () => {
        ses.destroy()
        await edge.close()
    })

    const deliver = (unitId: string, actionId = 'email', flowId = 'flow-1', cc: string[] = []): Promise<unknown> =>
        ses
            .send(
                new SendEmailCommand({
                    FromEmailAddress: 'flows@www.example.com',
                    Destination: { ToAddresses: [`${unitId}@${UNIT_EMAIL_DOMAIN}`], CcAddresses: cc },
                    Content: {
                        Simple: {
                            Subject: { Data: 'Scenario delivery' },
                            Body: { Text: { Data: 'Scenario delivery' } },
                            Headers: [
                                {
                                    Name: 'X-PostHog-Tracking-Code',
                                    Value: new EmailTrackingCodeSigner(TRACKING_KEYS, '').generate({
                                        functionId: flowId,
                                        id: `invocation-${unitId}`,
                                        teamId: 7,
                                        state: { actionId },
                                    }),
                                },
                            ],
                        },
                    },
                })
            )
            .catch((error: Error) => error)

    const rejectNextSend = (): Promise<unknown> =>
        internalFetch(`${edge.url}/_faults`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ name: 'ses.reject', params: { type: 'rejected' }, dose: { count: 1 } }),
        })

    const answerNextSendWith = (status: number, type: string): void => {
        edge.addFault({
            name: `ses.${type}`,
            answer: { kind: 'status', answer: { status, type, message: type } },
            dose: { count: 1 },
        })
    }

    const dropNextSend = (): void => {
        edge.addFault({ name: 'ses.drop', answer: { kind: 'drop-connection' }, dose: { count: 1 } })
    }

    const offered = (answer: JournalEntry['answer'] = { accepted: true }): JournalEntry => ({
        unitId: UNIT,
        kind: 'event',
        teamId: 7,
        offeredAt: Date.now(),
        answer,
        expect: { deliveries: ['email'] },
    })

    it.each<[string, JournalEntry, () => Promise<unknown>, object]>([
        ['delivered once', offered(), () => deliver(UNIT), { passed: true, observed: 0, unitIds: [] }],
        [
            'delivered on a retry after a retried status',
            offered(),
            async () => {
                answerNextSendWith(503, 'ServiceUnavailable')
                await deliver(UNIT)
                await deliver(UNIT)
            },
            { passed: true, observed: 0 },
        ],
        [
            'ended on purpose by a terminal fault',
            offered(),
            async () => {
                await rejectNextSend()
                await deliver(UNIT)
            },
            { passed: true, observed: 0 },
        ],
        [
            'refused by the intake, so nothing is expected',
            offered({ accepted: false, transportError: 'broker down' }),
            () => Promise.resolve(),
            { passed: true, observed: 0 },
        ],
        [
            'never received by the edge',
            offered(),
            () => deliver('run-b-1'),
            {
                passed: false,
                observed: 1,
                violation: `${UNIT} email: the edge never received it`,
                unitIds: [UNIT],
            },
        ],
        [
            'delivered for another action only',
            offered(),
            () => deliver(UNIT, 'webhook'),
            { passed: false, observed: 1, unitIds: [UNIT] },
        ],
        [
            'answered only with a retried status',
            offered(),
            async () => {
                answerNextSendWith(503, 'ServiceUnavailable')
                await deliver(UNIT)
            },
            {
                passed: false,
                observed: 1,
                violation: `${UNIT} email: the last of 1 attempts was answered 503`,
                unitIds: [UNIT],
            },
        ],
        [
            'answered only with a throttling status',
            offered(),
            async () => {
                answerNextSendWith(429, 'TooManyRequestsException')
                await deliver(UNIT)
            },
            {
                passed: false,
                observed: 1,
                violation: `${UNIT} email: the last of 1 attempts was answered 429`,
                unitIds: [UNIT],
            },
        ],
        [
            'answered only with a throttling error type on a 400',
            offered(),
            async () => {
                answerNextSendWith(400, 'ThrottlingException')
                await deliver(UNIT)
            },
            {
                passed: false,
                observed: 1,
                violation: `${UNIT} email: the last of 1 attempts was answered 400`,
                unitIds: [UNIT],
            },
        ],
        [
            'whose only attempt lost its connection',
            offered(),
            async () => {
                dropNextSend()
                await deliver(UNIT)
            },
            {
                passed: false,
                observed: 1,
                violation: `${UNIT} email: the last of 1 attempts was answered 0`,
                unitIds: [UNIT],
                crossedBy: UNIT,
            },
        ],
    ])('at_least_once for a unit %s', async (_story, entry, act, expected) => {
        judge.record(entry)
        await act()

        const [result] = await judge.check([{ name: 'at_least_once', params: {} }], {}, NO_RESETS)

        expect(result).toMatchObject({ name: 'at_least_once', ...expected })
    })

    it.each<[string, number[], boolean]>([
        ['a redirect, which fetch does not follow or retry, on the only attempt', [302], true],
        ['a status fetch does not retry, on the only attempt', [400], true],
        ['a request timeout, which fetch retries, on the only attempt', [408], false],
        ['a server error on fewer attempts than fetch makes', [503, 503], false],
        ['a server error on every attempt fetch makes', [503, 503, 503], true],
    ])('at_least_once for a webhook a fault answered with %s', (_story, statuses, passed) => {
        const attempts = statuses.map(
            (status, i): TruthRecord => ({
                seq: i + 1,
                at: new Date().toISOString(),
                kind: 'webhook',
                status,
                fault: 'dest.status',
                unitId: UNIT,
                actionId: 'webhook',
                detail: {},
            })
        )

        const result = atLeastOnce.check(
            {
                journal: [{ ...offered(), expect: { deliveries: ['webhook'] } }],
                truth: attempts,
                fetchRetries: 3,
                janitorResets: 0,
                boundary: { truthFrom: 0, horizon: { seq: 0, at: 0 }, unobserved: [] },
            },
            undefined,
            {}
        )

        expect(result.passed).toBe(passed)
    })

    const deliverTwice = async (unitId: string): Promise<void> => {
        await deliver(unitId)
        await deliver(unitId)
    }

    it.each<[string, () => Promise<unknown>, number, number | undefined, object]>([
        ['delivered once', () => deliver(UNIT), 0, undefined, { passed: true, observed: 0, unitIds: [] }],
        [
            'accepted only on a retry',
            async () => {
                answerNextSendWith(503, 'ServiceUnavailable')
                await deliver(UNIT)
                await deliver(UNIT)
            },
            0,
            undefined,
            { passed: true, observed: 0 },
        ],
        [
            'accepted twice with no job reset',
            () => deliverTwice(UNIT),
            0,
            undefined,
            {
                passed: false,
                observed: 1,
                violation: `${UNIT} email: accepted 2 times; 1 duplicate against 0 jobs the janitor reset`,
                unitIds: [UNIT],
            },
        ],
        ['accepted twice under a gate of one', () => deliverTwice(UNIT), 0, 1, { passed: true, observed: 1, gate: 1 }],
        [
            'accepted twice, as two others were, with three jobs reset',
            async () => {
                await deliverTwice(UNIT)
                await deliverTwice('run-a-2')
                await deliverTwice('run-a-3')
            },
            3,
            undefined,
            { passed: true, observed: 3 },
        ],
        [
            'accepted twice, as two others were, with one job reset under a gate of one',
            async () => {
                await deliverTwice(UNIT)
                await deliverTwice('run-a-2')
                await deliverTwice('run-a-3')
            },
            1,
            1,
            {
                passed: false,
                observed: 3,
                gate: 1,
                violation: `${UNIT} email: accepted 2 times; 3 duplicates against 1 job the janitor reset plus a gate of 1`,
            },
        ],
        [
            'accepted three times with two jobs reset',
            async () => {
                await deliverTwice(UNIT)
                await deliver(UNIT)
            },
            2,
            undefined,
            { passed: true, observed: 2, unitIds: [UNIT] },
        ],
        [
            'accepted three times with one job reset',
            async () => {
                await deliverTwice(UNIT)
                await deliver(UNIT)
            },
            1,
            undefined,
            {
                passed: false,
                observed: 2,
                violation: `${UNIT} email: accepted 3 times; 2 duplicates against 1 job the janitor reset`,
                unitIds: [UNIT],
                crossedBy: UNIT,
            },
        ],
    ])('duplicate_sends for a unit %s', async (_story, act, janitorResets, gate, expected) => {
        judge.record(offered())
        await act()

        const [result] = await judge.check(
            [{ name: 'duplicate_sends', params: {} }],
            gate === undefined ? {} : { duplicate_sends: gate },
            { ...NO_RESETS, janitorResets }
        )

        expect(result).toMatchObject({ name: 'duplicate_sends', ...expected })
    })

    it('crosses the duplicate_sends gate at the step whose unit counted every extra acceptance', async () => {
        const units = [
            { ...offered(), unitId: UNIT, offeredAt: 1_000, step: 0 },
            { ...offered(), unitId: 'run-a-2', offeredAt: 2_000, step: 1 },
        ]
        units.forEach((unit) => judge.record(unit))
        await deliverTwice(UNIT)
        await deliver(UNIT)
        await deliverTwice('run-a-2')

        const [result] = await judge.check([{ name: 'duplicate_sends', params: {} }], { duplicate_sends: 1 }, NO_RESETS)

        expect({
            passed: result.passed,
            observed: result.observed,
            crossedAtStep: units.find(({ unitId }) => unitId === result.crossedBy)?.step,
        }).toEqual({ passed: false, observed: 3, crossedAtStep: 0 })
    })

    it.each<[string, JournalEntry['kind'], JournalEntry['answer'], number | undefined, object]>([
        ['accepted', 'transactional', { accepted: true }, undefined, { passed: true, observed: 0, unitIds: [] }],
        [
            'refused with a status',
            'transactional',
            { accepted: false, status: 422, outcome: 'recipient_suppressed' },
            undefined,
            {
                passed: false,
                observed: 1,
                violation: `${UNIT}: the intake answered 422 recipient_suppressed`,
                unitIds: [UNIT],
                crossedBy: UNIT,
            },
        ],
        [
            'never reached',
            'transactional',
            { accepted: false, transportError: 'connect ECONNREFUSED' },
            undefined,
            {
                passed: false,
                observed: 1,
                violation: `${UNIT}: the intake could not be reached: connect ECONNREFUSED`,
            },
        ],
        [
            'refused under a gate of one',
            'transactional',
            { accepted: false, status: 503 },
            1,
            { passed: true, observed: 1 },
        ],
        [
            'of events the runner could not produce, which no intake answered',
            'event',
            { accepted: false, transportError: 'Local: Message timed out' },
            undefined,
            { passed: true, observed: 0, unitIds: [] },
        ],
    ])('refused_at_intake for a unit %s', async (_story, kind, answer, gate, expected) => {
        judge.record({ ...offered(answer), kind })

        const [result] = await judge.check(
            [{ name: 'refused_at_intake', params: {} }],
            gate === undefined ? {} : { refused_at_intake: gate },
            NO_RESETS
        )

        expect(result).toMatchObject({ name: 'refused_at_intake', ...expected })
    })

    const ADDRESS = `${UNIT}@${UNIT_EMAIL_DOMAIN}`
    const CC = 'manager@example.com'
    const SCHEDULED_PAST_THE_HORIZON = 1_000_000

    it.each<[string, JournalEntry, () => Promise<unknown>, Record<string, unknown>, object]>([
        ['delivered once', offered(), () => deliver(UNIT), {}, { passed: true, observed: 0, missing: [], extra: [] }],
        [
            'resent: accepted twice with no valve applied',
            offered(),
            () => deliverTwice(UNIT),
            {},
            {
                passed: false,
                observed: 1,
                violation: `${UNIT} email to ${ADDRESS} from flow-1: accepted 2 times, expected 1`,
                missing: [],
                extra: [UNIT],
            },
        ],
        [
            'dropped, while a unit of another run was accepted',
            offered(),
            () => deliver('run-b-1'),
            {},
            {
                passed: false,
                observed: 1,
                violation: `${UNIT} email: accepted 0 times by the recovery horizon, expected 1`,
                missing: [UNIT],
                extra: [],
            },
        ],
        [
            'accepted once after a retried status',
            offered(),
            async () => {
                answerNextSendWith(503, 'ServiceUnavailable')
                await deliverTwice(UNIT)
            },
            {},
            { passed: true, observed: 0 },
        ],
        [
            'with a follow-up the intake accepted, accepted once from each flow',
            { ...offered(), followUp: { accepted: true } },
            async () => {
                await deliver(UNIT)
                await deliver(UNIT, 'email', 'follow-up-flow')
            },
            {},
            { passed: true, observed: 0 },
        ],
        [
            'with a follow-up the intake accepted, whose first flow sent twice and follow-up never',
            { ...offered(), followUp: { accepted: true } },
            () => deliverTwice(UNIT),
            {},
            {
                passed: false,
                observed: 2,
                violation: `${UNIT} email to ${ADDRESS}: accepted from 1 flow by the recovery horizon, expected 2; ${UNIT} email to ${ADDRESS} from flow-1: accepted 2 times, expected 1`,
                missing: [UNIT],
                extra: [UNIT],
            },
        ],
        [
            'with a follow-up the intake accepted, whose first flow sent three times and follow-up never',
            { ...offered(), followUp: { accepted: true } },
            async () => {
                await deliverTwice(UNIT)
                await deliver(UNIT)
            },
            {},
            { passed: false, observed: 3, missing: [UNIT], extra: [UNIT] },
        ],
        [
            "with a follow-up the intake accepted, which reached only one of the first send's recipients",
            { ...offered(), followUp: { accepted: true } },
            async () => {
                await deliver(UNIT, 'email', 'flow-1', [CC])
                await deliver(UNIT, 'email', 'follow-up-flow')
            },
            {},
            {
                passed: false,
                observed: 1,
                violation: `${UNIT} email to ${CC}: accepted from 1 flow by the recovery horizon, expected 2`,
                missing: [UNIT],
                extra: [],
            },
        ],
        [
            'sent under an action the journal never listed',
            offered(),
            async () => {
                await deliver(UNIT)
                await deliver(UNIT, 'sms')
            },
            {},
            {
                passed: false,
                observed: 1,
                violation: `${UNIT} sms to ${ADDRESS}: accepted 1 time, expected 0`,
                missing: [],
                extra: [UNIT],
            },
        ],
        [
            'whose intake reply was lost, accepted once',
            offered({ accepted: false, transportError: 'socket hang up' }),
            () => deliver(UNIT),
            {},
            { passed: true, observed: 0 },
        ],
        [
            'whose intake reply was lost, accepted twice',
            offered({ accepted: false, transportError: 'socket hang up' }),
            () => deliverTwice(UNIT),
            {},
            { passed: false, observed: 1, extra: [UNIT] },
        ],
        [
            'refused with a status, yet accepted',
            { ...offered({ accepted: false, status: 503 }), kind: 'transactional' },
            () => deliver(UNIT),
            {},
            {
                passed: false,
                observed: 1,
                violation: `${UNIT} email to ${ADDRESS}: accepted 1 time, expected 0`,
                extra: [UNIT],
            },
        ],
        [
            'that expects no email and was sent none',
            { ...offered(), expect: { deliveries: [] } },
            () => Promise.resolve(),
            {},
            { passed: true, observed: 0 },
        ],
        [
            'that expects no email, yet was sent one',
            { ...offered(), expect: { deliveries: [] } },
            () => deliver(UNIT),
            {},
            { passed: false, observed: 1, extra: [UNIT] },
        ],
        [
            'scheduled past the horizon and not sent yet',
            { ...offered(), expect: { deliveries: ['email'], dueAt: SCHEDULED_PAST_THE_HORIZON } },
            () => Promise.resolve(),
            {},
            { passed: true, observed: 0 },
        ],
        [
            'scheduled past the horizon, yet accepted early',
            { ...offered(), expect: { deliveries: ['email'], dueAt: SCHEDULED_PAST_THE_HORIZON } },
            () => deliver(UNIT),
            {},
            { passed: false, observed: 1, extra: [UNIT] },
        ],
        [
            'ended by a fault the caller never retries',
            offered(),
            async () => {
                await rejectNextSend()
                await deliver(UNIT)
            },
            {},
            { passed: false, observed: 1, missing: [UNIT] },
        ],
    ])('no_loss for a unit %s', async (_story, entry, act, params, expected) => {
        judge.record(entry)
        await act()
        await judge.converge(20, NEVER_ABORTED)

        const [result] = await judge.check([{ name: 'no_loss', params }], {}, NO_RESETS)

        expect(result).toMatchObject({ name: 'no_loss', ...expected })
    })

    it.each<[string, () => Promise<unknown>, object]>([
        [
            'its only send',
            () => Promise.resolve(),
            {
                passed: false,
                violation: `${UNIT} email: accepted 0 times by the recovery horizon, expected 1`,
                missing: [UNIT],
            },
        ],
        [
            'a resend',
            () => deliver(UNIT),
            {
                passed: false,
                observed: 1,
                violation: `${UNIT} email to ${ADDRESS} from flow-1: accepted 2 times, expected 1`,
                missing: [],
                extra: [UNIT],
            },
        ],
    ])(
        'counts a send after the recovery horizon as extra, never as delivered: %s',
        async (_story, before, expected) => {
            judge.record(offered())
            await before()
            await judge.converge(20, NEVER_ABORTED)
            await deliver(UNIT)

            const [result] = await judge.check([{ name: 'no_loss', params: {} }], {}, NO_RESETS)

            expect(result).toMatchObject(expected)
        }
    )

    it.each<[string, () => Promise<unknown>, Array<() => Promise<unknown>>, object]>([
        ['a resend', () => deliver(UNIT), [() => deliver(UNIT)], { passed: false, observed: 1, extra: [UNIT] }],
        [
            'a retried status, then the retry',
            () => Promise.resolve(),
            [
                () => {
                    answerNextSendWith(503, 'ServiceUnavailable')
                    return deliver(UNIT)
                },
                () => deliver(UNIT),
            ],
            { passed: true, observed: 0 },
        ],
    ])(
        'counts what the edge accepted while convergence read a zero job count: %s',
        async (_story, before, duringCounts, expected) => {
            judge.record(offered())
            await before()
            duringProbe = () => duringCounts.shift()?.() ?? Promise.resolve()
            const convergence = await judge.converge(100, NEVER_ABORTED)

            const [result] = await judge.check([{ name: 'no_loss', params: {} }], {}, NO_RESETS)

            expect({ convergence, result }).toMatchObject({ convergence: { converged: true }, result: expected })
        }
    )

    it.each<[string, () => Promise<unknown>, RunEvidence, string]>([
        [
            'convergence was interrupted',
            () => judge.converge(20, AbortSignal.abort()),
            NO_RESETS,
            'the run reached no recovery horizon: convergence was interrupted',
        ],
        [
            'the last truth read failed',
            async () => {
                await judge.converge(20, NEVER_ABORTED)
                truthFails = 'The operation was aborted due to timeout'
            },
            NO_RESETS,
            'the truth could not be read: The operation was aborted due to timeout',
        ],
        [
            'a valve was never observed',
            () => judge.converge(20, NEVER_ABORTED),
            { ...NO_RESETS, unobserved: ['role.kill on cdp-cyclotron-worker-email was not observed: never applied'] },
            'role.kill on cdp-cyclotron-worker-email was not observed: never applied',
        ],
        [
            'the edge accepted a unit of this run that the journal never recorded',
            async () => {
                await deliver('run-a-2')
                await judge.converge(20, NEVER_ABORTED)
            },
            NO_RESETS,
            'the journal is incomplete: the edge accepted run-a-2 email, which the journal never recorded',
        ],
        [
            'the truth it read skips a seq',
            async () => {
                truthLoses = 1
                await deliver('run-b-1')
                await judge.converge(20, NEVER_ABORTED)
            },
            NO_RESETS,
            'the truth skips from seq 0 to 2',
        ],
    ])('leaves no_loss unjudged when %s', async (_story, act, run, unjudged) => {
        judge.record(offered())
        await deliver(UNIT)
        await act()

        const [result] = await judge.check([{ name: 'no_loss', params: {} }], {}, run)

        expect(result).toMatchObject({ name: 'no_loss', passed: false, unjudged })
    })

    const TEAM = 2_100_000_000
    const BACKLOG: Backlog = {
        teams: 1,
        jobs: { hogflow: 4 },
        stateBytes: { p50: 100, p90: 200, p99: 300 },
        compressibility: 0.5,
        parkFor: '10080m',
        tolerance: 0,
    }
    const RESIDENT = { name: 'resident', backlog: BACKLOG }
    const seededFor = (profile: string, rows: ResidentBacklog['found']): ResidentBacklog['seeded'] => ({
        profile,
        backlog: BACKLOG,
        rows,
    })
    const group = (
        rows: number,
        changed: Partial<ResidentBacklog['found'][number]> = {}
    ): ResidentBacklog['found'][number] => ({
        teamId: TEAM,
        queue: 'hogflow',
        status: 'available',
        rows,
        transitions: 0,
        stateBytes: rows * 100,
        ...changed,
    })

    it.each<[string, ResidentBacklog | undefined, object]>([
        [
            'every seeded row is still there',
            { profile: RESIDENT, seeded: seededFor('resident', [group(4)]), found: [group(4)] },
            { passed: true, observed: 0 },
        ],
        [
            'a row was lost',
            {
                profile: RESIDENT,
                seeded: seededFor('resident', [group(4), group(4, { teamId: TEAM + 1 })]),
                found: [group(4), group(3, { teamId: TEAM + 1 })],
            },
            { passed: false, observed: 1, violation: 'team 2100000001 hogflow available: expected 4 rows, found 3' },
        ],
        [
            'a parked row woke and completed',
            {
                profile: RESIDENT,
                seeded: seededFor('resident', [group(4)]),
                found: [group(3), group(1, { status: 'completed', transitions: 2 })],
            },
            { passed: false, observed: 3, violation: 'team 2100000000 hogflow available: expected 4 rows, found 3' },
        ],
        [
            'a worker took a parked row and parked it again',
            {
                profile: RESIDENT,
                seeded: seededFor('resident', [group(4)]),
                found: [group(4, { transitions: 2 })],
            },
            {
                passed: false,
                observed: 2,
                violation:
                    'team 2100000000 hogflow available: the rows changed in place, expected 0 transitions and 400 state bytes, found 2 and 400',
            },
        ],
        [
            "a row's state was cut short",
            {
                profile: RESIDENT,
                seeded: seededFor('resident', [group(4)]),
                found: [group(4, { stateBytes: 310 })],
            },
            {
                passed: false,
                observed: 1,
                violation:
                    'team 2100000000 hogflow available: the rows changed in place, expected 0 transitions and 400 state bytes, found 0 and 310',
            },
        ],
        [
            'a row moved to another queue',
            {
                profile: RESIDENT,
                seeded: seededFor('resident', [group(4)]),
                found: [group(3), group(1, { queue: 'email' })],
            },
            { passed: false, observed: 2, violation: 'team 2100000000 email available: expected 0 rows, found 1' },
        ],
        [
            'the backlog was seeded for another profile',
            { profile: RESIDENT, seeded: seededFor('synthetic', [group(4)]), found: [group(4)] },
            {
                passed: false,
                violation:
                    'the resident backlog was seeded for profile synthetic; run seed-backlog with profile resident first',
            },
        ],
        [
            'the profile changed its backlog since the seed',
            {
                profile: { name: 'resident', backlog: { ...BACKLOG, jobs: { hogflow: 8 } } },
                seeded: seededFor('resident', [group(4)]),
                found: [group(4)],
            },
            {
                passed: false,
                violation:
                    'the resident backlog was seeded from another backlog than profile resident holds; run seed-backlog with it again',
            },
        ],
        [
            'no backlog was seeded',
            { profile: RESIDENT, found: [] },
            {
                passed: false,
                violation: 'no resident backlog was seeded; run seed-backlog with this profile first',
            },
        ],
    ])('resident_backlog_intact when %s', async (_story, backlog, expected) => {
        resident = backlog

        const [result] = await judge.check([{ name: 'resident_backlog_intact', params: {} }], {}, NO_RESETS)

        expect(result).toMatchObject({ name: 'resident_backlog_intact', ...expected })
    })

    it.each<[string, 'bounce' | 'rejected' | undefined, FollowUpAnswer | undefined, object]>([
        [
            'bounced, then refused as suppressed',
            'bounce',
            { accepted: false, status: 422, outcome: 'recipient_suppressed' },
            { passed: true, observed: 0, unitIds: [] },
        ],
        [
            'bounced, then not followed up',
            'bounce',
            { notSent: 'the edge recorded no SES feedback within 60s' },
            {
                passed: false,
                observed: 1,
                violation: `${UNIT}: the follow-up was not sent: the edge recorded no SES feedback within 60s`,
                unitIds: [UNIT],
            },
        ],
        [
            'bounced, with no follow-up',
            'bounce',
            undefined,
            { passed: false, observed: 1, violation: `${UNIT}: no follow-up was offered`, unitIds: [UNIT] },
        ],
        [
            'bounced, then accepted again',
            'bounce',
            { accepted: true },
            { passed: false, observed: 1, violation: `${UNIT}: cdp-api accepted the follow-up` },
        ],
        [
            'bounced, then refused for another reason',
            'bounce',
            { accepted: false, status: 503 },
            { passed: false, observed: 1, violation: `${UNIT}: cdp-api answered the follow-up 503` },
        ],
        ['never bounced, then accepted again', undefined, { accepted: true }, { passed: true, observed: 0 }],
        [
            'never bounced, then not followed up',
            undefined,
            { notSent: 'the edge recorded no SES feedback within 60s' },
            {
                passed: false,
                observed: 1,
                violation: `${UNIT}: the follow-up was not sent: the edge recorded no SES feedback within 60s`,
            },
        ],
        [
            'rejected rather than bounced, then not followed up',
            'rejected',
            { notSent: 'the edge recorded no SES feedback within 60s' },
            { passed: true, observed: 0 },
        ],
    ])('bounced_suppressed for a unit %s', async (_story, rejectType, followUp, expected) => {
        if (rejectType) {
            await internalFetch(`${edge.url}/_faults`, {
                method: 'POST',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify({ name: 'ses.reject', params: { type: rejectType }, dose: { count: 1 } }),
            })
        }
        await deliver(UNIT)
        judge.record({ ...offered(), followUp })

        const [result] = await judge.check([{ name: 'bounced_suppressed', params: {} }], {}, NO_RESETS)

        expect(result).toMatchObject({ name: 'bounced_suppressed', ...expected })
    })

    it.each<[string, string[], object]>([
        ['after the last bounce', ['run-a-2', UNIT], { passed: true, observed: 0 }],
        ['before a later bounce', [UNIT, 'run-a-2'], { passed: false, observed: 1, unitIds: [UNIT] }],
    ])(
        'bounced_suppressed for a unit the edge took without a bounce %s, then not followed up',
        async (_story, deliveryOrder, expected) => {
            for (const unitId of deliveryOrder) {
                if (unitId === 'run-a-2') {
                    await internalFetch(`${edge.url}/_faults`, {
                        method: 'POST',
                        headers: { 'content-type': 'application/json' },
                        body: JSON.stringify({ name: 'ses.reject', params: { type: 'bounce' }, dose: { count: 1 } }),
                    })
                }
                await deliver(unitId)
            }
            judge.record({ ...offered(), followUp: { notSent: 'the edge took the first send without a bounce' } })

            const [result] = await judge.check([{ name: 'bounced_suppressed', params: {} }], {}, NO_RESETS)

            expect(result).toMatchObject(expected)
        }
    )

    it.each<[string, () => Judge]>([
        ['reopened', () => judge],
        ['opened fresh', judgeOf],
    ])('ignores what the edge recorded before a run %s', async (_story, nextJudge) => {
        await deliver(UNIT)
        judge = nextJudge()
        await judge.open(SEED)
        judge.record(offered())

        const [result] = await judge.check([{ name: 'at_least_once', params: {} }], {}, NO_RESETS)

        expect(result).toMatchObject({ passed: false, unitIds: [UNIT] })
    })

    it.each<[string, number, boolean, number, object]>([
        ['jobs are still unfinished', 3, true, 10, { converged: false, unfinishedJobs: 3, unrecorded: [] }],
        ['a delivery has no record', 0, false, 10, { converged: false, unfinishedJobs: 0, unrecorded: [UNIT] }],
        ['the queues are empty and every delivery is recorded', 0, true, 10, { converged: true, unfinishedJobs: 0 }],
        [
            'the last poll answers only after the deadline',
            0,
            true,
            200,
            { converged: false, unfinishedJobs: 0, unrecorded: [] },
        ],
    ])(
        'converges only when no job is unfinished and every delivery is recorded within the deadline: %s',
        async (_story, jobs, delivered, pollTakesMs, expected) => {
            unfinishedJobs = jobs
            probeTakesMs = pollTakesMs
            judge.record(offered())
            if (delivered) {
                await deliver(UNIT)
            }

            expect(await judge.converge(50, NEVER_ABORTED)).toMatchObject(expected)
        }
    )

    it('ends at its deadline with the truth it read and the read that failed, rather than throwing', async () => {
        judge.record(offered())
        await deliver(UNIT)
        truthFails = 'The operation was aborted due to timeout'

        const convergence = await judge.converge(50, NEVER_ABORTED)

        expect(convergence).toEqual({
            converged: false,
            unfinishedJobs: null,
            unrecorded: [UNIT],
            tookMs: expect.any(Number),
            unread: 'The operation was aborted due to timeout',
        })
    })

    it.each<[string, () => void, number, number | null]>([
        [
            'as unknown when its last job count fails after an earlier poll counted some',
            () => {
                probeAnswers = 1
            },
            50,
            null,
        ],
        [
            'it counted when the truth read after that count fails',
            () => {
                duringProbe = () => {
                    truthFails = 'The operation was aborted due to timeout'
                    return Promise.resolve()
                }
            },
            20,
            5,
        ],
    ])('reports the unfinished jobs %s', async (_story, failing, withinMs, reported) => {
        unfinishedJobs = 5
        failing()
        judge.record(offered())
        await deliver(UNIT)

        const convergence = await judge.converge(withinMs, NEVER_ABORTED)

        expect(convergence).toEqual({
            converged: false,
            unfinishedJobs: reported,
            unrecorded: [],
            tookMs: expect.any(Number),
            unread: 'The operation was aborted due to timeout',
        })
    })

    it('judges on the truth it already read when its last read fails, and names the failed read', async () => {
        judge.record(offered())
        await deliver(UNIT)
        await judge.converge(50, NEVER_ABORTED)
        truthFails = 'The operation was aborted due to timeout'

        const [result] = await judge.check([{ name: 'at_least_once', params: {} }], {}, NO_RESETS)

        expect({ result, unread: judge.evidence().unread }).toEqual({
            result: expect.objectContaining({ passed: true }),
            unread: 'The operation was aborted due to timeout',
        })
    })
})
