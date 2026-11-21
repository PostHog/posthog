import http from 'http'
import { AddressInfo } from 'net'

import { HogFlowSchema } from '~/cdp/schema/hogflow'
import {
    TEMPLATE_SEND_TOKEN_CLAIMS,
    TransactionalEmailRequestSchema,
} from '~/cdp/services/hogflows/transactional-email'
import { PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { parseJSON } from '~/common/utils/json-parse'

import { UNIT_EMAIL_DOMAIN } from '../provider-edge'
import { OfferContext, TRAFFIC, bounceFollowup, captureWebhook, retryDelayMsOf, transactionalEmail } from './traffic'

const SECRET = 'scenario-transactional-secret'
const UNIT = { unitId: 'run-a-1', teamId: 7, flowId: 'flow-7' }
const ROUTE = `/api/projects/${UNIT.teamId}/hog_flows/${UNIT.flowId}/transactional_email`

type Answer = { status: number; body: object; retryAfter?: string }

const NEVER_ABORTED = new AbortController().signal

function startCdpApi(
    ...answers: Answer[]
): Promise<{ url: string; received: object[]; answered: Promise<void>; close(): Promise<void> }> {
    let markAnswered = (): void => undefined
    const answered = new Promise<void>((resolve) => (markAnswered = resolve))
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
            res.writeHead(answer.status, {
                'content-type': 'application/json',
                ...(answer.retryAfter !== undefined && { 'retry-after': answer.retryAfter }),
            }).end(JSON.stringify(answer.body), markAnswered)
        })
    })
    return new Promise((resolve) =>
        server.listen(0, '127.0.0.1', () =>
            resolve({
                url: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
                received,
                answered,
                close: () => new Promise((closed) => server.close(() => closed())),
            })
        )
    )
}

const contextFor = (url: string, settled: string | undefined = undefined): OfferContext => ({
    emit: () => Promise.reject(new Error('the transactional kind never emits')),
    cdpApi: { url, jwt: new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_SEND_TRANSACTIONAL_EMAIL, SECRET) },
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
            ['accepts a queued send', { status: 202, body: { status: 'queued' } }, { accepted: true }],
            [
                'journals a refusal with its status and outcome',
                { status: 422, body: { error: 'recipient_suppressed' } },
                { accepted: false, status: 422, outcome: 'recipient_suppressed' },
            ],
        ])(
            '%s from the template route, called with a token for the team and flow',
            async (_story, answer, expected) => {
                const cdpApi = await startCdpApi(answer)
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

        it('journals a transport error when cdp-api cannot be reached', async () => {
            const cdpApi = await startCdpApi({ status: 202, body: {} })
            await cdpApi.close()

            expect(await transactionalEmail.offer(UNIT, contextFor(cdpApi.url), NEVER_ABORTED)).toEqual({
                accepted: false,
                transportError: expect.stringContaining('ECONNREFUSED'),
            })
        })

        const UNAVAILABLE: Answer = { status: 503, body: { error: 'intake_unavailable' }, retryAfter: '0' }

        it.each<[string, Answer[], object, number]>([
            [
                'retries a 5xx with the same key and journals the retry',
                [UNAVAILABLE, { status: 202, body: { status: 'queued' } }],
                { accepted: true, retries: 1 },
                2,
            ],
            [
                'stops retrying after three retries and journals the last refusal',
                [UNAVAILABLE],
                { accepted: false, status: 503, outcome: 'intake_unavailable', retries: 3 },
                4,
            ],
        ])('%s', async (_story, answers, expected, sends) => {
            const cdpApi = await startCdpApi(...answers)
            try {
                expect(await transactionalEmail.offer(UNIT, contextFor(cdpApi.url), NEVER_ABORTED)).toEqual(expected)
                expect(cdpApi.received).toHaveLength(sends)
                expect(new Set(cdpApi.received.map((request) => JSON.stringify(request))).size).toBe(1)
            } finally {
                await cdpApi.close()
            }
        })

        it('stops waiting out a Retry-After when the run aborts', async () => {
            const cdpApi = await startCdpApi({ ...UNAVAILABLE, retryAfter: '30' })
            const abort = new AbortController()
            try {
                const offered = transactionalEmail.offer(UNIT, contextFor(cdpApi.url), abort.signal)
                await cdpApi.answered
                abort.abort()

                await expect(offered).rejects.toMatchObject({ name: 'AbortError' })
                expect(cdpApi.received).toHaveLength(1)
            } finally {
                await cdpApi.close()
            }
        })

        it.each<[string, Parameters<typeof retryDelayMsOf>[0], number | undefined]>([
            ['waits the seconds Retry-After asks for', { status: 503, retryAfter: '2', retry: 0, keyed: true }, 2000],
            ['backs off without a Retry-After', { status: 500, retryAfter: null, retry: 2, keyed: true }, 2000],
            [
                'backs off past a Retry-After it cannot read',
                { status: 503, retryAfter: 'soon', retry: 0, keyed: true },
                500,
            ],
            ['caps a long Retry-After', { status: 503, retryAfter: '120', retry: 0, keyed: true }, 10_000],
            ['never retries an unkeyed send', { status: 503, retryAfter: '0', retry: 0, keyed: false }, undefined],
            ['never retries a refusal under 500', { status: 429, retryAfter: '0', retry: 0, keyed: true }, undefined],
            ['stops after three retries', { status: 503, retryAfter: '0', retry: 3, keyed: true }, undefined],
        ])('%s', (_story, attempt, expected) => {
            expect(retryDelayMsOf(attempt)).toBe(expected)
        })
    })
})

describe('bounce_followup traffic', () => {
    it.each<[string, string | undefined, object, number]>([
        [
            'sends the follow-up through the template route once its feedback settled',
            undefined,
            { accepted: false, status: 422, outcome: 'recipient_suppressed' },
            1,
        ],
        [
            'leaves the follow-up unsent when its feedback did not settle',
            'the edge recorded no SES feedback within 60s',
            { notSent: 'the edge recorded no SES feedback within 60s' },
            0,
        ],
    ])('%s', async (_story, settled, expected, sends) => {
        const cdpApi = await startCdpApi({ status: 422, body: { error: 'recipient_suppressed' } })
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
