import { createInMemoryJobQueue, createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import http, { Server } from 'http'
import { AddressInfo } from 'net'
import express from 'ultimate-express'

import { insertHogFunctionTemplate } from '~/cdp/_tests/fixtures'
import { insertHogFlow } from '~/cdp/_tests/fixtures-hogflows'
import { CdpApi } from '~/cdp/cdp-api'
import { HogFlowSchema } from '~/cdp/schema/hogflow'
import {
    TEMPLATE_SEND_TOKEN_CLAIMS,
    TransactionalEmailRequestSchema,
} from '~/cdp/services/hogflows/transactional-email'
import { template as incomingWebhookTemplate } from '~/cdp/templates/_sources/webhook/incoming_webhook.template'
import { PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { setupExpressApp } from '~/common/api/router'
import { KAFKA_CDP_INTAKE_WORKFLOW_WEBHOOK } from '~/common/config/kafka-topics'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { parseJSON } from '~/common/utils/json-parse'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import { UNIT_EMAIL_DOMAIN } from '../provider-edge'
import {
    OfferContext,
    REAL_CLOCK,
    SendClock,
    TRAFFIC,
    bounceFollowup,
    captureWebhook,
    transactionalEmail,
    workflowWebhook,
} from './traffic'

const SECRET = 'scenario-transactional-secret'
const UNIT = { unitId: 'run-a-1', teamId: 7, flowId: 'flow-7' }
const ROUTE = `/api/projects/${UNIT.teamId}/hog_flows/${UNIT.flowId}/transactional_email`

type Answer = { status: number; body: object; takesMs?: number }

const NEVER_ABORTED = new AbortController().signal

type FakeCdpApi = {
    url: string
    received: object[]
    receivedAt: number[]
    close(): Promise<void>
}

type ServerClock = { now(): number; pass?(ms: number): void }

function startCdpApi(answers: Answer[], clock: ServerClock = { now: Date.now }): Promise<FakeCdpApi> {
    const receivedAt: number[] = []

    const verifier = new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_SEND_TRANSACTIONAL_EMAIL, SECRET)
    const received: object[] = []
    const server = http.createServer((req, res) => {
        let raw = ''
        req.on('data', (chunk) => (raw += chunk))
        req.on('end', () => {
            const claims = verifier.verify(String(req.headers.authorization).replace(/^Bearer /, ''))
            const authorized =
                claims.team_id === UNIT.teamId &&
                claims.hog_flow_id === UNIT.flowId &&
                claims.kind === TEMPLATE_SEND_TOKEN_CLAIMS.kind
            const body = TransactionalEmailRequestSchema.strict().parse(parseJSON(raw))
            const answer = answers[Math.min(received.length, answers.length - 1)]
            received.push({ method: req.method, url: req.url, authorized, body })
            receivedAt.push(clock.now())
            clock.pass?.(answer.takesMs ?? 0)
            res.writeHead(answer.status, { 'content-type': 'application/json' }).end(JSON.stringify(answer.body))
        })
    })
    return new Promise((resolve) =>
        server.listen(0, '127.0.0.1', () =>
            resolve({
                url: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
                received,
                receivedAt,
                close: () => new Promise((closed) => server.close(() => closed())),
            })
        )
    )
}

const contextFor = (url: string, settled: string | undefined = undefined, clock?: SendClock): OfferContext => ({
    emit: () => Promise.reject(new Error('the transactional kind never emits')),
    cdpApi: {
        nextUrl: () => url,
        jwt: new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_SEND_TRANSACTIONAL_EMAIL, SECRET),
        clock,
    },
    sesFeedback: { settled: (unitId) => Promise.resolve(unitId === UNIT.unitId ? settled : 'another unit') },
})

describe('traffic', () => {
    it.each(
        TRAFFIC.filter((kind) => kind !== captureWebhook).flatMap((kind) =>
            [0, 2].map((parks) => [kind.name, parks, kind] as const)
        )
    )('%s parks its flow %i times on a short delay before its action', async (_name, parks, kind) => {
        const flow = HogFlowSchema.parse(await kind.flow(UNIT.teamId, 3, parks))
        const next = (from: string): string | undefined => flow.edges.find((edge) => edge.from === from)?.to
        const walked: object[] = []
        for (let id: string | undefined = 'trigger'; id !== undefined; id = next(id)) {
            const { type, config } = flow.actions.find((action) => action.id === id)!
            walked.push(type === 'delay' ? { type, config } : { type })
        }

        expect(walked).toEqual([
            { type: 'trigger' },
            ...Array.from({ length: parks }, () => ({ type: 'delay', config: { delay_duration: '1s' } })),
            { type: kind.deliveries[0] === 'webhook' ? 'function' : 'function_email' },
            { type: 'exit' },
        ])
    })

    describe('transactional_email', () => {
        it.each<[string, Answer, object]>([
            [
                'accepts a queued send',
                { status: 202, body: { status: 'queued' } },
                { accepted: true, attemptsMs: [expect.any(Number)] },
            ],
            [
                'journals a refusal with its status and outcome',
                { status: 422, body: { error: 'recipient_suppressed' } },
                { accepted: false, status: 422, outcome: 'recipient_suppressed', attemptsMs: [expect.any(Number)] },
            ],
        ])(
            '%s from the template route, called with a token for the team and flow',
            async (_story, answer, expected) => {
                const cdpApi = await startCdpApi([answer])
                try {
                    expect(await transactionalEmail.offer(UNIT, contextFor(cdpApi.url), NEVER_ABORTED)).toEqual(
                        expected
                    )
                    expect(cdpApi.received).toEqual([
                        {
                            method: 'POST',
                            url: ROUTE,
                            authorized: true,
                            body: {
                                to: `${UNIT.unitId}@${UNIT_EMAIL_DOMAIN}`,
                                distinct_id: UNIT.unitId,
                                variables: {},
                                idempotency_key: UNIT.unitId,
                            },
                        },
                    ])
                } finally {
                    await cdpApi.close()
                }
            }
        )

        it.each<[string, (context: OfferContext) => OfferContext, string]>([
            ['cdp-api cannot be reached', (context) => context, 'ECONNREFUSED'],
            [
                'the signer cannot mint a token',
                (context) => ({
                    ...context,
                    cdpApi: {
                        ...context.cdpApi!,
                        jwt: {
                            mint: () => {
                                throw new Error('signing key unavailable')
                            },
                        } as unknown as ScopedServiceJwt,
                    },
                }),
                'signing key unavailable',
            ],
        ])('journals a transport error when %s', async (_story, contextOf, error) => {
            const cdpApi = await startCdpApi([{ status: 202, body: {} }])
            await cdpApi.close()

            expect(await transactionalEmail.offer(UNIT, contextOf(contextFor(cdpApi.url)), NEVER_ABORTED)).toEqual({
                accepted: false,
                transportError: expect.stringContaining(error),
            })
        })

        const UNAVAILABLE: Answer = { status: 503, body: { error: 'intake_unavailable' } }

        it("ends the real clock's wait when the run aborts while it is pending", async () => {
            const abort = new AbortController()
            const waiting = REAL_CLOCK.wait(60_000, abort.signal)
            abort.abort()

            await expect(waiting).rejects.toMatchObject({ name: 'AbortError' })
        })

        describe('on a controlled clock', () => {
            const controlledClock = (...stalls: number[]): SendClock & Required<ServerClock> => {
                let now = 0
                return {
                    now: () => now,
                    pass: (ms) => {
                        now += ms
                    },
                    wait: (ms) => {
                        now += ms + (stalls.shift() ?? 0)
                        return Promise.resolve()
                    },
                }
            }

            it('retries a 5xx with the same key after half a second and journals the retry', async () => {
                const clock = controlledClock()
                const cdpApi = await startCdpApi([UNAVAILABLE, { status: 202, body: { status: 'queued' } }], clock)
                try {
                    expect(
                        await transactionalEmail.offer(UNIT, contextFor(cdpApi.url, undefined, clock), NEVER_ABORTED)
                    ).toEqual({ accepted: true, retries: 1, attemptsMs: [0, 0] })
                    expect(cdpApi.receivedAt).toEqual([0, 500])
                    expect(new Set(cdpApi.received.map((request) => JSON.stringify(request))).size).toBe(1)
                } finally {
                    await cdpApi.close()
                }
            })

            it('backs off from half a second to five, retries until a minute after the first send, then journals the last refusal', async () => {
                const clock = controlledClock()
                const cdpApi = await startCdpApi(
                    [{ status: 500, body: { error: 'internal_error' } }, UNAVAILABLE],
                    clock
                )
                const backoffs = [500, 1000, 2000, 4000, ...Array.from({ length: 10 }, () => 5000)]
                try {
                    expect(
                        await transactionalEmail.offer(UNIT, contextFor(cdpApi.url, undefined, clock), NEVER_ABORTED)
                    ).toEqual({
                        accepted: false,
                        status: 503,
                        outcome: 'intake_unavailable',
                        retries: backoffs.length,
                        attemptsMs: [0, ...backoffs.map(() => 0)],
                    })
                    expect(cdpApi.receivedAt).toEqual(
                        backoffs.reduce((sentAt, backoff) => [...sentAt, sentAt[sentAt.length - 1] + backoff], [0])
                    )
                    expect(new Set(cdpApi.received.map((request) => JSON.stringify(request))).size).toBe(1)
                } finally {
                    await cdpApi.close()
                }
            })

            it.each<[string, number[], Answer, number]>([
                ['its backoff overruns the deadline', [60_000], UNAVAILABLE, 0],
                [
                    'its first refusal arrives a quarter second before the deadline',
                    [],
                    { ...UNAVAILABLE, takesMs: 59_750 },
                    59_750,
                ],
            ])('sends no retry, and times its one answer, when %s', async (_story, stalls, first, answerMs) => {
                const clock = controlledClock(...stalls)
                const cdpApi = await startCdpApi([first, { status: 202, body: { status: 'queued' } }], clock)
                try {
                    expect(
                        await transactionalEmail.offer(UNIT, contextFor(cdpApi.url, undefined, clock), NEVER_ABORTED)
                    ).toEqual({ accepted: false, status: 503, outcome: 'intake_unavailable', attemptsMs: [answerMs] })
                    expect(cdpApi.received).toHaveLength(1)
                } finally {
                    await cdpApi.close()
                }
            })

            it.each<[string, (signal: AbortSignal, abort: AbortController) => Promise<void>]>([
                [
                    'during its backoff',
                    (signal) =>
                        new Promise((_resolve, reject) =>
                            signal.addEventListener('abort', () => reject(signal.reason), { once: true })
                        ),
                ],
                [
                    'as its backoff ends',
                    (_signal, abort) => {
                        abort.abort()
                        return Promise.resolve()
                    },
                ],
            ])('stops retrying when the run aborts %s', async (_when, backOff) => {
                let waiting = (): void => undefined
                const backingOff = new Promise<void>((resolve) => (waiting = resolve))
                const abort = new AbortController()
                const clock: SendClock = {
                    now: () => 0,
                    wait: (_ms, signal) => {
                        const backedOff = backOff(signal, abort)
                        waiting()
                        return backedOff
                    },
                }
                const cdpApi = await startCdpApi([UNAVAILABLE])
                try {
                    const offered = transactionalEmail.offer(
                        UNIT,
                        contextFor(cdpApi.url, undefined, clock),
                        abort.signal
                    )
                    await Promise.race([backingOff, offered.catch(() => undefined)])
                    abort.abort()

                    await expect(offered).rejects.toMatchObject({ name: 'AbortError' })
                    expect(cdpApi.received).toHaveLength(1)
                } finally {
                    await cdpApi.close()
                }
            })
        })
    })

    describe('workflow_webhook', () => {
        let hub: Hub
        let api: CdpApi
        let server: Server
        let url: string
        let teamId: number

        beforeEach(async () => {
            hub = await createHub({})
            teamId = (await createTestTeamFixture(hub.postgres)).team.id
            await insertHogFunctionTemplate(hub.postgres, incomingWebhookTemplate)
            api = new CdpApi(hub, createCdpConsumerDeps(hub), {
                hogQueue: createMockJobQueue(),
                hogflowQueue: createInMemoryJobQueue(),
            })
            await api.start()
            const app: express.Application = setupExpressApp()
            app.use('/', api.router())
            await new Promise<void>((resolve) => {
                server = app.listen(0, '127.0.0.1', resolve)
            })
            url = `http://127.0.0.1:${(app as unknown as { port: number }).port}`
        })

        afterEach(async () => {
            server.close()
            await api.stop()
            await closeHub(hub)
        })

        const producedRuns = (): { job: { id: string; state: { state: { event: object } } } }[] =>
            mockProducerObserver
                .getProducedKafkaMessagesForTopic(KAFKA_CDP_INTAKE_WORKFLOW_WEBHOOK)
                .map((message) => message.value as never)

        it("retries its seeded flow's webhook under the unit's key, so the retried runs share one id and the next unit gets its own", async () => {
            const flow = await insertHogFlow(hub.postgres, await workflowWebhook.flow(teamId, 0, 1))
            const unit = { unitId: 'run-w-1', teamId, flowId: flow.id }
            const next = { ...unit, unitId: 'run-w-2' }
            mockProducerObserver.produceSpy.mockImplementationOnce(() =>
                Promise.reject(new Error('Broker: Not enough in-sync replicas'))
            )
            let now = 0
            const clock: SendClock = {
                now: () => now,
                wait: (ms) => {
                    now += ms
                    return Promise.resolve()
                },
            }

            const answer = await workflowWebhook.offer(unit, contextFor(url, undefined, clock), NEVER_ABORTED)
            await workflowWebhook.offer(next, contextFor(url, undefined, clock), NEVER_ABORTED)

            const runs = producedRuns()
            expect(answer).toEqual({ accepted: true, retries: 1, attemptsMs: [expect.any(Number), expect.any(Number)] })
            expect(runs.map(({ job }) => job.state.state.event)).toEqual(
                [unit, unit, next].map(({ unitId }) =>
                    expect.objectContaining({ distinct_id: unitId, properties: { unit_id: unitId } })
                )
            )
            const [first, retried, other] = runs.map(({ job }) => job.id)
            expect(retried).toBe(first)
            expect(other).not.toBe(first)
        })
    })
})

describe('bounce_followup traffic', () => {
    it.each<[string, string | undefined, object, number]>([
        [
            'sends the follow-up through the template route once its feedback settled',
            undefined,
            { accepted: false, status: 422, outcome: 'recipient_suppressed', attemptsMs: [expect.any(Number)] },
            1,
        ],
        [
            'leaves the follow-up unsent when its feedback did not settle',
            'the edge recorded no SES feedback within 60s',
            { notSent: 'the edge recorded no SES feedback within 60s' },
            0,
        ],
    ])('%s', async (_story, settled, expected, sends) => {
        const cdpApi = await startCdpApi([{ status: 422, body: { error: 'recipient_suppressed' } }])
        try {
            expect(
                await bounceFollowup.followUp!.offer(
                    UNIT,
                    contextFor(cdpApi.url, settled),
                    new AbortController().signal
                )
            ).toEqual(expected)
            expect(cdpApi.received).toHaveLength(sends)
        } finally {
            await cdpApi.close()
        }
    })
})
