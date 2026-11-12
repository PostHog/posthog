import { SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'

import { EmailTrackingCodeSigner } from '~/cdp/services/messaging/helpers/tracking-code'
import { internalFetch } from '~/common/utils/request'

import { ProviderEdge, TruthRecord, UNIT_EMAIL_DOMAIN, startProviderEdge } from '../provider-edge'
import { atLeastOnce } from './invariants'
import { JournalEntry, Judge, createJudge } from './judge'

const TRACKING_KEYS = 'scenario-tracking-key'
const UNIT = 'run-a-1'
const SEED = { teamIds: [7] }
const NEVER_ABORTED = new AbortController().signal

describe('judge', () => {
    let edge: ProviderEdge
    let ses: SESv2Client
    let unfinishedJobs: number
    let clockMs: number
    let probeTakesMs: number
    let judge: Judge

    const judgeOf = (): Judge =>
        createJudge({
            edgeUrl: edge.url,
            probe: {
                unfinishedJobs: () => {
                    clockMs += probeTakesMs
                    return Promise.resolve(unfinishedJobs)
                },
            },
            pollMs: 10,
            now: () => clockMs,
        })

    beforeEach(async () => {
        edge = await startProviderEdge({ port: 0, trackingKeys: TRACKING_KEYS })
        ses = new SESv2Client({
            endpoint: edge.url,
            region: 'us-east-1',
            credentials: { accessKeyId: 'edge', secretAccessKey: 'edge' },
            maxAttempts: 1,
        })
        unfinishedJobs = 0
        clockMs = 0
        probeTakesMs = 10
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
            },
        ],
    ])('at_least_once for a unit %s', async (_story, entry, act, expected) => {
        judge.record(entry)
        await act()

        const [result] = await judge.check([{ name: 'at_least_once', params: {} }], {})

        expect(result).toMatchObject({ name: 'at_least_once', ...expected })
    })

    it.each<[string, number, boolean]>([
        ['a status fetch does not retry', 400, true],
        ['a request timeout, which fetch retries', 408, false],
        ['too many requests, which fetch retries', 429, false],
        ['a server error, which fetch retries', 503, false],
    ])('at_least_once for a webhook whose only attempt a fault answered with %s', (_story, status, passed) => {
        const webhook: TruthRecord = {
            seq: 1,
            at: new Date().toISOString(),
            kind: 'webhook',
            status,
            fault: 'dest.status',
            unitId: UNIT,
            actionId: 'webhook',
            detail: {},
        }

        const result = atLeastOnce.check(
            { journal: [{ ...offered(), expect: { deliveries: ['webhook'] } }], truth: [webhook] },
            undefined
        )

        expect(result.passed).toBe(passed)
    })

    it.each<[string, () => Promise<unknown>, number | undefined, object]>([
        ['delivered once', () => deliver(UNIT), undefined, { passed: true, observed: 0, unitIds: [] }],
        [
            'accepted only on a retry',
            async () => {
                answerNextSendWith(503, 'ServiceUnavailable')
                await deliver(UNIT)
                await deliver(UNIT)
            },
            undefined,
            { passed: true, observed: 0 },
        ],
        [
            'accepted twice',
            async () => {
                await deliver(UNIT)
                await deliver(UNIT)
            },
            undefined,
            { passed: false, observed: 1, violation: `${UNIT} email: accepted 2 times`, unitIds: [UNIT] },
        ],
        [
            'accepted twice under a gate of one',
            async () => {
                await deliver(UNIT)
                await deliver(UNIT)
            },
            1,
            { passed: true, observed: 1, gate: 1 },
        ],
    ])('duplicate_sends for a unit %s', async (_story, act, gate, expected) => {
        judge.record(offered())
        await act()

        const [result] = await judge.check(
            [{ name: 'duplicate_sends', params: {} }],
            gate === undefined ? {} : { duplicate_sends: gate }
        )

        expect(result).toMatchObject({ name: 'duplicate_sends', ...expected })
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
            gate === undefined ? {} : { refused_at_intake: gate }
        )

        expect(result).toMatchObject({ name: 'refused_at_intake', ...expected })
    })

    it.each<[string, () => Judge]>([
        ['reopened', () => judge],
        ['opened fresh', judgeOf],
    ])('ignores what the edge recorded before a run %s', async (_story, nextJudge) => {
        await deliver(UNIT)
        judge = nextJudge()
        await judge.open(SEED)
        judge.record(offered())

        const [result] = await judge.check([{ name: 'at_least_once', params: {} }], {})

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
})
