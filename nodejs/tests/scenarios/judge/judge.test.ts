import { SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'
import { mkdtempSync, rmSync } from 'fs'
import http from 'http'
import { AddressInfo } from 'net'
import os from 'os'
import path from 'path'

import { EmailTrackingCodeSigner } from '~/cdp/services/messaging/helpers/tracking-code'
import { internalFetch } from '~/common/utils/request'

import type { ResidentBacklog } from '../backlog/backlog'
import type { Backlog } from '../cards'
import { ProviderEdge, TruthRecord, UNIT_EMAIL_DOMAIN, startProviderEdge } from '../provider-edge'
import { Truth } from '../provider-edge/truth'
import { atLeastOnce } from './invariants'
import { FollowUpAnswer, JournalEntry, Judge, createJudge } from './judge'
import { TruthSource, edgeTruth } from './truth'

const TRACKING_KEYS = 'scenario-tracking-key'
const UNIT = 'run-a-1'
const NO_RESETS = { janitorResets: 0 }
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
                        return edgeTruth(edge.url).after(cursor, read)
                    }
                    clockMs += probeTakesMs
                    return Promise.reject(new Error(truthFails))
                },
            },
            probe: {
                unfinishedJobs: () => {
                    clockMs += probeTakesMs
                    polls += 1
                    return polls > probeAnswers
                        ? Promise.reject(new Error('The operation was aborted due to timeout'))
                        : Promise.resolve(unfinishedJobs)
                },
            },
            fetchRetries: 3,
            residentBacklog: () => Promise.resolve(resident!),
            finalRead: { attempts: 2, backoffMs: 0 },
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
        polls = 0
        probeAnswers = Infinity
        judge = judgeOf()
        await judge.open(SEED)
    })

    afterEach(async () => {
        ses.destroy()
        await edge.close()
    })

    const deliver = (unitId: string, actionId = 'email'): Promise<unknown> =>
        ses
            .send(
                new SendEmailCommand({
                    FromEmailAddress: 'flows@www.example.com',
                    Destination: { ToAddresses: [`${unitId}@${UNIT_EMAIL_DOMAIN}`] },
                    Content: {
                        Simple: {
                            Subject: { Data: 'Scenario delivery' },
                            Body: { Text: { Data: 'Scenario delivery' } },
                            Headers: [
                                {
                                    Name: 'X-PostHog-Tracking-Code',
                                    Value: new EmailTrackingCodeSigner(TRACKING_KEYS, '').generate({
                                        functionId: 'flow-1',
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
                ...NO_RESETS,
            },
            undefined
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
            { janitorResets }
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

    it('reports the unfinished jobs as unknown when its last poll fails after an earlier poll counted some', async () => {
        unfinishedJobs = 5
        probeAnswers = 1
        judge.record(offered())
        await deliver(UNIT)

        const convergence = await judge.converge(50, NEVER_ABORTED)

        expect(convergence).toEqual({
            converged: false,
            unfinishedJobs: null,
            unrecorded: [],
            tookMs: expect.any(Number),
            unread: 'The operation was aborted due to timeout',
        })
    })

    it('judges on the truth it already read when its last read fails, and names the failed read', async () => {
        judge.record(offered())
        await deliver(UNIT)
        await judge.converge(50, NEVER_ABORTED)
        await deliver('run-a-2')
        truthFails = 'The operation was aborted due to timeout'

        const [result] = await judge.check([{ name: 'at_least_once', params: {} }], {}, NO_RESETS)

        expect({ result, unread: judge.evidence().unread }).toEqual({
            result: expect.objectContaining({ passed: true }),
            unread: 'the truth read hit a harness limit at record 1 of 2: 2 of 2 attempts failed, the last with The operation was aborted due to timeout',
        })
    })

    describe('reading a large truth', () => {
        const LARGE_TRUTH_RECORDS = 1_500_000
        const PAGE = 1000
        const POLL_BOUND_MS = 100
        const FINAL_BOUND_MS = 5000
        const SLOW_PAGE_MS = 300

        type PageFault = 'slow' | 'reset' | 'empty' | 'stale' | undefined

        let truth: Truth
        let edge: ProviderEdge
        let front: http.Server
        let faultOf: (after: number) => PageFault
        let heads: number
        let headsAnswered: number

        beforeEach(async () => {
            truth = new Truth()
            heads = 0
            headsAnswered = Infinity
            edge = await startProviderEdge({ port: 0, truth })
            front = http.createServer((req, res) => {
                const url = new URL(req.url ?? '/', edge.url)
                if (url.pathname === '/_truth/head' && ++heads > headsAnswered) {
                    res.writeHead(200, { 'content-type': 'application/json' })
                    res.end('{}')
                    return
                }
                const fault = url.pathname === '/_truth' ? faultOf(Number(url.searchParams.get('after'))) : undefined
                if (fault === 'reset') {
                    req.socket.destroy()
                }
                if (fault === 'empty' || fault === 'stale') {
                    const after = Number(url.searchParams.get('after'))
                    const records = fault === 'stale' ? truth.page(after - 1, 1).records : []
                    res.writeHead(200, { 'content-type': 'application/json' })
                    res.end(JSON.stringify({ records, next: after + 1 }))
                }
                if (fault !== undefined && fault !== 'slow') {
                    return
                }
                const forward = (): void => {
                    http.get(`${edge.url}${req.url}`, (answer) => {
                        res.writeHead(answer.statusCode ?? 502, answer.headers)
                        answer.pipe(res)
                    })
                }
                if (fault === 'slow') {
                    setTimeout(forward, SLOW_PAGE_MS)
                    return
                }
                forward()
            })
            await new Promise<void>((resolve) => front.listen(0, '127.0.0.1', resolve))
        })

        afterEach(async () => {
            front.closeAllConnections()
            await new Promise<void>((resolve) => front.close(() => resolve()))
            await edge.close()
        })

        const readOf = (records: TruthRecord[]): { read: number; inOrder: boolean } => ({
            read: records.length,
            inOrder: records.every(({ seq }, i) => seq === i + 1),
        })

        const append = (records: number): void => {
            for (let i = 1; i <= records; i++) {
                truth.append({ kind: 'ses.send', status: 200, unitId: `run-a-${i}`, actionId: 'email', detail: {} })
            }
        }

        const slowAt = (at: number) => (): ((after: number) => PageFault) => (after) =>
            after === at ? 'slow' : undefined

        const resettingOnce = (at: number) => (): ((after: number) => PageFault) => {
            let reset = false
            return (after) => (after === at && !reset && (reset = true) ? 'reset' : undefined)
        }

        const resettingFrom = (at: number) => (): ((after: number) => PageFault) => (after) =>
            after >= at ? 'reset' : undefined

        const recordingMoreOnTheFirstPage = (more: number) => (): ((after: number) => PageFault) => (after) => {
            if (after === 0) {
                append(more)
            }
            return undefined
        }

        const answeringFrom = (at: number, fault: PageFault) => (): ((after: number) => PageFault) => (after) =>
            after >= at ? fault : undefined

        const judgeOf = (backoffMs: number, around = (source: TruthSource): TruthSource => source): Judge =>
            createJudge({
                truth: around(
                    edgeTruth(`http://127.0.0.1:${(front.address() as AddressInfo).port}`, {
                        pollMs: POLL_BOUND_MS,
                        finalMs: FINAL_BOUND_MS,
                    })
                ),
                probe: { unfinishedJobs: () => Promise.resolve(0) },
                fetchRetries: 3,
                finalRead: { attempts: 3, backoffMs },
            })

        it.each<[string, number, () => (after: number) => PageFault, object]>([
            [
                'reads all of it when one page answers slower than a converge poll waits',
                LARGE_TRUTH_RECORDS,
                slowAt(LARGE_TRUTH_RECORDS / 2),
                { read: LARGE_TRUTH_RECORDS, unread: undefined },
            ],
            [
                'reads all of it when one page request fails once',
                3 * PAGE,
                resettingOnce(PAGE),
                { read: 3 * PAGE, unread: undefined },
            ],
            [
                'reads up to the head it took first, leaving out what the edge records after it',
                1.5 * PAGE,
                recordingMoreOnTheFirstPage(PAGE),
                { read: 1.5 * PAGE, unread: undefined },
            ],
            [
                'keeps what it read and names a harness limit when the edge stops answering',
                3 * PAGE,
                resettingFrom(2 * PAGE),
                {
                    read: 2 * PAGE,
                    unread: expect.stringMatching(
                        /^the truth read hit a harness limit at record 2000 of 3000: 3 of 3 attempts failed, the last with /
                    ),
                },
            ],
            [
                'keeps what it read and names a harness limit when the edge answers an empty page before the head',
                3 * PAGE,
                answeringFrom(2 * PAGE, 'empty'),
                {
                    read: 2 * PAGE,
                    unread: 'the truth read hit a harness limit at record 2000 of 3000: the edge answered no records past 2000',
                },
            ],
            [
                'keeps what it read and names a harness limit when the edge answers the last record again',
                3 * PAGE,
                answeringFrom(2 * PAGE, 'stale'),
                {
                    read: 2 * PAGE,
                    unread: 'the truth read hit a harness limit at record 2000 of 3000: the edge answered no records past 2000',
                },
            ],
        ])('%s', async (_story, records, fault, expected) => {
            faultOf = fault()
            const judge = judgeOf(0)
            await judge.open(SEED)
            append(records)

            await judge.check([], {}, NO_RESETS)

            const { truth: read, unread } = judge.evidence()
            expect({ ...readOf(read), unread }).toEqual({ ...expected, inOrder: true })
        })

        const stoppingAt =
            (at: number, run: AbortController) =>
            (after: number): PageFault => {
                if (after !== at) {
                    return undefined
                }
                run.abort()
                return undefined
            }

        it.each<[string, (run: AbortController) => (after: number) => PageFault, number, string | RegExp]>([
            [
                'before it starts',
                (run) => {
                    run.abort()
                    return () => undefined
                },
                0,
                'the truth read hit a harness limit at record 0: the run was stopped',
            ],
            [
                'between pages the edge answers',
                (run) => stoppingAt(PAGE, run),
                2 * PAGE,
                'the truth read hit a harness limit at record 2000 of 3000: the run was stopped',
            ],
        ])('stops the read when the run is stopped %s', async (_story, fault, records, expected) => {
            const run = new AbortController()
            const judge = judgeOf(600_000)
            await judge.open(SEED)
            append(3 * PAGE)
            faultOf = fault(run)

            await judge.check([], {}, NO_RESETS, run.signal)

            const { truth: read, unread } = judge.evidence()
            expect({ ...readOf(read), unread }).toEqual({
                read: records,
                inOrder: true,
                unread: typeof expected === 'string' ? expected : expect.stringMatching(expected),
            })
        })

        it('stops the read when the run is stopped while it waits to retry a failed page', async () => {
            const run = new AbortController()
            const stoppingOnceTheBackoffStarts = (source: TruthSource): TruthSource => ({
                ...source,
                after: (cursor, read) =>
                    source.after(cursor, read).catch((error: unknown) => {
                        setImmediate(() => run.abort())
                        throw error
                    }),
            })
            const judge = judgeOf(600_000, stoppingOnceTheBackoffStarts)
            await judge.open(SEED)
            append(3 * PAGE)
            faultOf = resettingFrom(2 * PAGE)()

            await judge.check([], {}, NO_RESETS, run.signal)

            const { truth: read, unread } = judge.evidence()
            expect({ ...readOf(read), unread }).toEqual({
                read: 2 * PAGE,
                inOrder: true,
                unread: expect.stringMatching(
                    /^the truth read hit a harness limit at record 2000 of 3000: 1 of 3 attempts failed, the last with /
                ),
            })
        })

        it('keeps what it read and names a harness limit when the edge answers no head', async () => {
            faultOf = () => undefined
            headsAnswered = 1
            const judge = judgeOf(0)
            await judge.open(SEED)
            append(PAGE)

            await judge.check([], {}, NO_RESETS)

            const { truth: read, unread } = judge.evidence()
            expect({ ...readOf(read), unread }).toEqual({
                read: 0,
                inOrder: true,
                unread: 'the truth read hit a harness limit at record 0: the edge answered no head',
            })
        })
    })
})
