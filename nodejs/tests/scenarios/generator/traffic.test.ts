import Chance from 'chance'
import { createHash } from 'crypto'
import http from 'http'
import { AddressInfo } from 'net'

import { HogFlowSchema } from '~/cdp/schema/hogflow'
import { filesWorkflowShape } from '~/cdp/services/hogflows/files-workflow-shape'
import {
    ATTACHMENT_UPLOAD_TOKEN_CLAIMS,
    AcceptedSendRequestSchema,
    CODE_SEND_TOKEN_CLAIMS,
    TEMPLATE_SEND_TOKEN_CLAIMS,
    TransactionalEmailRequestSchema,
} from '~/cdp/services/hogflows/transactional-email'
import { PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { parseJSON } from '~/common/utils/json-parse'
import { waitForExpect } from '~/tests/helpers/expectations'

import { UNIT_EMAIL_DOMAIN } from '../provider-edge'
import {
    OfferContext,
    REAL_CLOCK,
    SendClock,
    TRAFFIC,
    bounceFollowup,
    captureWebhook,
    fileBytes,
    transactionalEmail,
    transactionalEmailFiles,
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
            (kind === transactionalEmailFiles ? [0] : [0, 2]).map((parks) => [kind.name, parks, kind] as const)
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

        it('journals a transport error when cdp-api cannot be reached', async () => {
            const cdpApi = await startCdpApi([{ status: 202, body: {} }])
            await cdpApi.close()

            expect(await transactionalEmail.offer(UNIT, contextFor(cdpApi.url), NEVER_ABORTED)).toEqual({
                accepted: false,
                transportError: expect.stringContaining('ECONNREFUSED'),
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
                    ).toEqual({ accepted: true, retries: 1 })
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
                    ).toEqual({ accepted: false, status: 503, outcome: 'intake_unavailable', retries: backoffs.length })
                    expect(cdpApi.receivedAt).toEqual(
                        backoffs.reduce((sentAt, backoff) => [...sentAt, sentAt[sentAt.length - 1] + backoff], [0])
                    )
                    expect(new Set(cdpApi.received.map((request) => JSON.stringify(request))).size).toBe(1)
                } finally {
                    await cdpApi.close()
                }
            })

            it.each<[string, number[], Answer]>([
                ['its backoff overruns the deadline', [60_000], UNAVAILABLE],
                [
                    'its first refusal arrives a quarter second before the deadline',
                    [],
                    { ...UNAVAILABLE, takesMs: 59_750 },
                ],
            ])('sends no retry when %s', async (_story, stalls, first) => {
                const clock = controlledClock(...stalls)
                const cdpApi = await startCdpApi([first, { status: 202, body: { status: 'queued' } }], clock)
                try {
                    expect(
                        await transactionalEmail.offer(UNIT, contextFor(cdpApi.url, undefined, clock), NEVER_ABORTED)
                    ).toEqual({ accepted: false, status: 503, outcome: 'intake_unavailable' })
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
})

const sha256Of = (bytes: Buffer): string => createHash('sha256').update(bytes).digest('hex')

const firstPutsAnswer = (first: Record<string, number>): ((sha256: string) => number) => {
    const answered = new Set<string>()
    return (sha256) => {
        const status = answered.has(sha256) ? 200 : first[sha256]
        answered.add(sha256)
        return status
    }
}

const checksumOf = (sha256: string): string => Buffer.from(sha256, 'hex').toString('base64')

type FilesAnswers = {
    uploads: Answer[]
    puts: number[] | ((sha256: string) => number)
    send: Answer
    putsHeld?: Promise<void>
}

type FilesCdpApi = { url: string; received: { route: string; body: unknown }[]; close(): Promise<void> }

function startFilesCdpApi({ uploads, puts, send, putsHeld }: FilesAnswers): Promise<FilesCdpApi> {
    const verifier = new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_SEND_TRANSACTIONAL_EMAIL, SECRET)
    const received: FilesCdpApi['received'] = []
    let url = ''
    const next = <T>(answers: T[], route: string): T =>
        answers[Math.min(received.filter((request) => request.route === route).length - 1, answers.length - 1)]
    const server = http.createServer((req, res) => {
        const chunks: Buffer[] = []
        req.on('data', (chunk: Buffer) => chunks.push(chunk))
        req.on('end', async () => {
            const raw = Buffer.concat(chunks)
            const claims = req.headers.authorization
                ? verifier.verify(String(req.headers.authorization).replace(/^Bearer /, ''))
                : {}
            const reply = ({ status, body }: Answer): void => {
                res.writeHead(status, { 'content-type': 'application/json' }).end(JSON.stringify(body))
            }
            if (req.method === 'PUT') {
                const sha256 = sha256Of(raw)
                const signed =
                    req.url === `/files/${sha256}` && req.headers['x-amz-checksum-sha256'] === checksumOf(sha256)
                received.push({ route: signed ? 'put' : 'unsigned put', body: sha256 })
                await putsHeld
                reply({ status: typeof puts === 'function' ? puts(sha256) : next(puts, 'put'), body: {} })
            } else if (req.url === `/api/projects/${UNIT.teamId}/transactional_email/attachments/uploads`) {
                const body = parseJSON(raw.toString()) as { files: { sha256: string }[] }
                received.push({
                    route: claims.kind === ATTACHMENT_UPLOAD_TOKEN_CLAIMS.kind ? 'uploads' : 'unauthorized',
                    body,
                })
                const answer = next(uploads, 'uploads')
                reply(
                    answer.status === 200 && Object.keys(answer.body).length === 0
                        ? {
                              status: 200,
                              body: {
                                  files: body.files.map(({ sha256 }) => ({
                                      sha256,
                                      status: 'upload',
                                      url: `${url}/files/${sha256}`,
                                      method: 'PUT',
                                      headers: { 'x-amz-checksum-sha256': checksumOf(sha256) },
                                  })),
                              },
                          }
                        : answer
                )
            } else {
                const authorized = claims.kind === CODE_SEND_TOKEN_CLAIMS.kind && claims.hog_flow_id === UNIT.flowId
                received.push({
                    route: authorized ? req.url! : 'unauthorized',
                    body: AcceptedSendRequestSchema.parse(parseJSON(raw.toString())),
                })
                reply(send)
            }
        })
    })
    return new Promise((resolve) =>
        server.listen(0, '127.0.0.1', () => {
            url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
            resolve({
                url,
                received,
                close: () =>
                    new Promise((closed) => {
                        server.closeAllConnections()
                        server.close(() => closed())
                    }),
            })
        })
    )
}

describe('transactional_email_files traffic', () => {
    const SEND_ROUTE = `${ROUTE}/send`
    const FILES = [
        { seed: 1, sizeBytes: 1000 },
        { seed: 2, sizeBytes: 200_000 },
    ]
    const SHAS = FILES.map((file) => sha256Of(fileBytes(file)))
    const QUEUED: Answer = { status: 202, body: { status: 'queued' } }
    const UPLOADED = {
        route: 'uploads',
        body: { files: FILES.map(({ sizeBytes }, i) => ({ sha256: SHAS[i], size: sizeBytes })) },
    }
    const PUTS = SHAS.map((sha256) => ({ route: 'put', body: sha256 }))
    const SENT = {
        route: SEND_ROUTE,
        body: {
            to: `${UNIT.unitId}@${UNIT_EMAIL_DOMAIN}`,
            distinct_id: UNIT.unitId,
            variables: {},
            idempotency_key: UNIT.unitId,
            send: {
                tracking: { captureEngagement: false },
                attachments: SHAS.map((sha256, i) => ({
                    sha256,
                    filename: `scenario-${i + 1}.pdf`,
                    content_type: 'application/pdf',
                })),
            },
        },
    }
    const clock = (): SendClock => {
        let now = 0
        return {
            now: () => now,
            wait: (ms) => {
                now += ms
                return Promise.resolve()
            },
        }
    }

    it.each<[string, typeof FILES, FilesAnswers, object, object[]]>([
        [
            'uploads each file, puts the bytes it hashed, then sends with the hashes',
            FILES,
            { uploads: [{ status: 200, body: {} }], puts: [200], send: QUEUED },
            { accepted: true, attachments: SHAS },
            [UPLOADED, ...PUTS, SENT],
        ],
        [
            'sends a unit without files through the code route without uploading',
            [],
            { uploads: [], puts: [], send: QUEUED },
            { accepted: true, attachments: [] },
            [{ route: SEND_ROUTE, body: { ...SENT.body, send: { tracking: { captureEngagement: false } } } }],
        ],
        [
            'uploads again and sends once the object store stops answering a put with a 5xx',
            FILES,
            { uploads: [{ status: 200, body: {} }], puts: [503, 503, 200], send: QUEUED },
            { accepted: true, retries: 1, attachments: SHAS },
            [UPLOADED, ...PUTS, UPLOADED, ...PUTS, SENT],
        ],
        [
            'uploads again once one put is refused and the other answers a 5xx, whatever order they land in',
            FILES,
            {
                uploads: [{ status: 200, body: {} }],
                puts: firstPutsAnswer({ [SHAS[0]]: 400, [SHAS[1]]: 503 }),
                send: QUEUED,
            },
            { accepted: true, retries: 1, attachments: SHAS },
            [UPLOADED, ...PUTS, UPLOADED, ...PUTS, SENT],
        ],
        [
            'journals a refused upload with its stage and sends nothing',
            FILES,
            { uploads: [{ status: 400, body: { error: 'message_too_large' } }], puts: [], send: QUEUED },
            { accepted: false, status: 400, outcome: 'uploads message_too_large', attachments: SHAS },
            [UPLOADED],
        ],
        [
            'journals an upload refusal without an error code as its stage alone',
            FILES,
            { uploads: [{ status: 400, body: { errors: [] } }], puts: [], send: QUEUED },
            { accepted: false, status: 400, outcome: 'uploads', attachments: SHAS },
            [UPLOADED],
        ],
        [
            'journals an upload reply without slots as a transport error and sends nothing',
            FILES,
            { uploads: [{ status: 200, body: { slots: [] } }], puts: [], send: QUEUED },
            {
                accepted: false,
                transportError: expect.stringMatching(/^uploads answered with no upload slots/),
                attachments: SHAS,
            },
            [UPLOADED],
        ],
        [
            'journals an upload reply that leaves a file without a slot as a transport error and sends nothing',
            FILES,
            { uploads: [{ status: 200, body: { files: [] } }], puts: [], send: QUEUED },
            {
                accepted: false,
                transportError: 'uploads answered slots for 0 files where 2 were asked',
                attachments: SHAS,
            },
            [UPLOADED],
        ],
    ])('%s', async (_story, files, answers, expected, requests) => {
        const sendClock = clock()
        const cdpApi = await startFilesCdpApi(answers)
        try {
            expect(
                await transactionalEmailFiles.offer(
                    { ...UNIT, files },
                    contextFor(cdpApi.url, undefined, sendClock),
                    NEVER_ABORTED
                )
            ).toEqual(expected)
            expect(cdpApi.received).toEqual(requests)
        } finally {
            await cdpApi.close()
        }
    })

    it('seeds a workflow that cdp-api takes files for', async () => {
        const flow = HogFlowSchema.parse(await transactionalEmailFiles.flow(UNIT.teamId, 3, 0))

        expect(filesWorkflowShape(flow)).toEqual({ emailStep: expect.objectContaining({ type: 'function_email' }) })
    })

    it('sends nothing to cdp-api once the run is interrupted while a put is pending', async () => {
        let releasePuts = (): void => {}
        const putsHeld = new Promise<void>((resolve) => (releasePuts = resolve))
        const cdpApi = await startFilesCdpApi({
            uploads: [{ status: 200, body: {} }],
            puts: [200],
            send: QUEUED,
            putsHeld,
        })
        const abort = new AbortController()
        try {
            const offered = transactionalEmailFiles.offer(
                { ...UNIT, files: FILES },
                contextFor(cdpApi.url),
                abort.signal
            )
            await waitForExpect(() => expect(cdpApi.received.filter(({ route }) => route === 'put')).toHaveLength(2))
            abort.abort()
            releasePuts()

            await expect(offered).rejects.toMatchObject({ name: 'AbortError' })
            expect(cdpApi.received.map(({ route }) => route)).toEqual(['uploads', 'put', 'put'])
        } finally {
            releasePuts()
            await cdpApi.close()
        }
    })

    it.each([1, 3, 5])('fills a file of %d bytes from its seed', (sizeBytes) => {
        expect(fileBytes({ seed: 1, sizeBytes })).not.toEqual(fileBytes({ seed: 2, sizeBytes }))
    })

    const PROFILE = { ratePerSecond: 1, files: { share: 1, perSend: 2, sizes: [{ bytes: 1000, weight: 1 }] } }

    it.each<[string, object, number[]]>([
        ['draws perSend files from the sizes for a send that carries files', PROFILE, [1000, 1000]],
        ['draws no files for a send outside the share', { ...PROFILE, files: { ...PROFILE.files, share: 0 } }, []],
    ])('%s', (_story, profile, sizes) => {
        const draw = (): object[] => transactionalEmailFiles.filesOf!(new Chance(5), profile)

        expect(draw().map((file) => (file as { sizeBytes: number }).sizeBytes)).toEqual(sizes)
        expect(draw()).toEqual(draw())
    })

    it.each<[string, object]>([
        ['parks a send with files', { ...PROFILE, parks: 1 }],
        [
            'asks for more files per send than one email holds',
            { ...PROFILE, files: { ...PROFILE.files, perSend: 2, sizes: [{ bytes: 20_000_000, weight: 1 }] } },
        ],
    ])('refuses a profile that %s', (_story, profile) => {
        expect(transactionalEmailFiles.profile.safeParse(profile).success).toBe(false)
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
