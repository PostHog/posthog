import { ProviderEdge, TruthRecord, startProviderEdge } from '.'
import { execFile } from 'child_process'
import { mkdtempSync, rmSync } from 'fs'
import http from 'http'
import { AddressInfo } from 'net'
import os from 'os'
import path from 'path'

import { EmailTrackingCodeSigner } from '~/cdp/services/messaging/helpers/tracking-code'
import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'
import { waitForExpect } from '~/tests/helpers/expectations'

const TRACKING_KEYS = 'scenario-tracking-key'
const BOUNCED = 'run-1-1@www.example.com'
const NODEJS = path.join(__dirname, '..', '..', '..')

type Received = { contentType: string | undefined; body: string }

describe('provider edge SES feedback', () => {
    let caDir: string
    let receiver: http.Server
    let received: Received[]
    let answer: number
    let edge: ProviderEdge
    const signer = new EmailTrackingCodeSigner(TRACKING_KEYS, 'https://track.example.com')

    beforeEach(async () => {
        caDir = mkdtempSync(path.join(os.tmpdir(), 'provider-edge-feedback-'))
        received = []
        answer = 200
        receiver = http.createServer((req, res) => {
            let body = ''
            req.on('data', (chunk) => (body += chunk))
            req.on('end', () => {
                received.push({ contentType: req.headers['content-type'], body })
                res.writeHead(answer, { 'content-type': 'application/json' }).end('{}')
            })
        })
        await new Promise<void>((resolve) => receiver.listen(0, '127.0.0.1', resolve))
        const { port } = receiver.address() as AddressInfo
        edge = await startProviderEdge({
            port: 0,
            caDir,
            trackingKeys: TRACKING_KEYS,
            feedbackUrl: `http://127.0.0.1:${port}/public/m/ses_webhook`,
            configurationSets: { 'scenario-tracking': { tracking: true }, 'scenario-untracked': { tracking: false } },
        })
    })

    afterEach(async () => {
        await edge.close()
        receiver.closeAllConnections()
        await new Promise<void>((resolve) => receiver.close(() => resolve()))
        rmSync(caDir, { recursive: true, force: true })
    })

    const control = async (method: string, route: string, body?: object): Promise<{ status: number; json: any }> => {
        const response = await internalFetch(`${edge.url}${route}`, {
            method,
            headers: { 'content-type': 'application/json' },
            body: body === undefined ? undefined : JSON.stringify(body),
        })
        const text = await response.text()
        return { status: response.status, json: text ? parseJSON(text) : undefined }
    }

    const truth = async (): Promise<TruthRecord[]> => (await control('GET', '/_truth')).json.records

    const sendTracked = async ({
        destination = { ToAddresses: [BOUNCED] },
        configurationSet = 'scenario-tracking',
    }: { destination?: object; configurationSet?: string | null } = {}): Promise<number> =>
        (
            await control('POST', '/v2/email/outbound-emails', {
                FromEmailAddress: 'flows@www.example.com',
                Destination: destination,
                Content: {
                    Simple: {
                        Subject: { Data: 'Hello' },
                        Body: { Text: { Data: 'Hello' } },
                        Headers: [
                            {
                                Name: 'X-PostHog-Tracking-Code',
                                Value: signer.generate({
                                    functionId: 'flow-1',
                                    id: 'invocation-1',
                                    teamId: 7,
                                    state: { actionId: 'email' },
                                }),
                            },
                        ],
                    },
                },
                EmailTags: [{ Name: 'ph_team', Value: '7' }],
                ConfigurationSetName: configurationSet ?? undefined,
            })
        ).status

    const bounceEverySend = async (): Promise<void> => {
        const added = await control('POST', '/_faults', {
            name: 'ses.reject',
            params: { type: 'bounce' },
            dose: { share: 1 },
        })
        expect(added.status).toBe(201)
    }

    type Handled = {
        status: number
        metrics: string[]
        hardBounced: string[]
        softBounced: string[]
        complained: string[]
        delivered: string[]
    }

    const handleInCdpApiProcess = (
        envelopes: string[]
    ): Promise<{ code: number | string; handled?: Handled[]; error?: string }> => {
        const script = `
            const { SesWebhookHandler } = require(${JSON.stringify(path.join(NODEJS, 'src/cdp/services/messaging/helpers/ses'))})
            const { EmailTrackingCodeSigner } = require(${JSON.stringify(path.join(NODEJS, 'src/cdp/services/messaging/helpers/tracking-code'))})
            const handler = new SesWebhookHandler(new EmailTrackingCodeSigner(${JSON.stringify(TRACKING_KEYS)}, 'https://track.example.com'))
            const addresses = (groups) => (groups ?? []).flatMap(({ emailAddresses }) => emailAddresses)
            Promise.all(JSON.parse(process.env.SNS_ENVELOPES).map((envelope) =>
                handler.handleWebhook({ body: JSON.parse(envelope), verifySignature: true }).then((result) => ({
                    status: result.status,
                    metrics: (result.metrics ?? []).map(({ metricName }) => metricName),
                    hardBounced: addresses(result.hardBounceRecipients),
                    softBounced: addresses(result.transientBounceRecipients),
                    complained: addresses(result.complainedRecipients),
                    delivered: addresses(result.deliveredRecipients),
                }))
            )).then(
                (handled) => process.stdout.write(JSON.stringify(handled)),
                (error) => process.stdout.write('error: ' + error.message)
            ).finally(() => process.exit(0))
        `
        const { EXTERNAL_REQUEST_PROXY_TEAMS: _rollout, ...inherited } = process.env
        return new Promise((resolve) =>
            execFile(
                path.join(NODEJS, 'node_modules', '.bin', 'tsx'),
                ['-e', script],
                {
                    timeout: 30_000,
                    env: {
                        ...inherited,
                        SNS_ENVELOPES: JSON.stringify(envelopes),
                        HTTPS_PROXY: edge.url,
                        NODE_EXTRA_CA_CERTS: edge.caCertPath,
                    },
                },
                (error, stdout) => {
                    const code = error ? (error.code ?? String(error.signal)) : 0
                    resolve(
                        stdout.startsWith('error: ')
                            ? { code, error: stdout }
                            : { code, handled: stdout ? parseJSON(stdout) : undefined }
                    )
                }
            )
        )
    }

    const eventTypeOf = ({ body }: Received): string => {
        const { eventType, bounce } = parseJSON((parseJSON(body) as { Message: string }).Message) as {
            eventType: string
            bounce?: { bounceType: string }
        }
        return bounce ? `${eventType}:${bounce.bounceType}` : eventType
    }

    const countsOf = (types: string[]): Record<string, number> =>
        Object.fromEntries([...Map.groupBy(types, (type) => type)].map(([type, all]) => [type, all.length]))

    it('posts a signed hard bounce that the SES webhook handler verifies through its own certificate fetch and suppresses', async () => {
        await bounceEverySend()

        expect(await sendTracked()).toBe(200)
        await waitForExpect(() => expect(received).toHaveLength(1), 5000, 10)
        const handled = await handleInCdpApiProcess([received[0].body])

        expect({ contentType: received[0].contentType, ...handled }).toEqual({
            contentType: expect.stringMatching(/^text\/plain/),
            code: 0,
            handled: [expect.objectContaining({ status: 200, hardBounced: [BOUNCED] })],
        })
    }, 60_000)

    it('bounces every recipient of a send, Cc and Bcc included', async () => {
        const [cc, bcc] = ['run-1-2@www.example.com', 'run-1-3@www.example.com']
        await bounceEverySend()

        await sendTracked({ destination: { ToAddresses: [BOUNCED], CcAddresses: [cc], BccAddresses: [bcc] } })
        await waitForExpect(() => expect(received).toHaveLength(1), 5000, 10)

        const record = parseJSON((parseJSON(received[0].body) as { Message: string }).Message) as {
            bounce: { bouncedRecipients: { emailAddress: string }[] }
        }
        expect(record.bounce.bouncedRecipients.map(({ emailAddress }) => emailAddress)).toEqual([BOUNCED, cc, bcc])
    })

    it('posts a bounce for a send on the configuration set without open and click tracking', async () => {
        await bounceEverySend()

        expect(await sendTracked({ configurationSet: 'scenario-untracked' })).toBe(200)

        await waitForExpect(() => expect(received).toHaveLength(1), 5000, 10)
    })

    it('posts no feedback for a send that names no configuration set, and records why', async () => {
        await bounceEverySend()

        expect(await sendTracked({ configurationSet: null })).toBe(200)

        await waitForExpect(
            async () =>
                expect((await truth()).filter(({ kind }) => kind === 'ses.feedback')).toEqual([
                    expect.objectContaining({
                        status: 0,
                        detail: { error: 'The send names no configuration set, so SES publishes no events for it.' },
                    }),
                ]),
            5000,
            10
        )
        expect(received).toEqual([])
    })

    it.each([
        ['added before', 'throttle first'],
        ['added after', 'bounce first'],
    ])('counts a bounced send against a throttle %s it, because it goes out', async (_story, order) => {
        const clock = jest.spyOn(Date, 'now').mockReturnValue(Date.now())
        const throttle = { name: 'ses.throttle', params: { rate: 1 } }
        const bounce = { name: 'ses.reject', params: { type: 'bounce' }, dose: { share: 1 } }
        const added: number[] = []
        const answers: number[] = []
        try {
            for (const fault of order === 'throttle first' ? [throttle, bounce] : [bounce, throttle]) {
                added.push((await control('POST', '/_faults', fault)).status)
            }
            answers.push(await sendTracked(), await sendTracked())
        } finally {
            clock.mockRestore()
        }

        expect({ added, answers }).toEqual({ added: [201, 201], answers: [200, 429] })
        await waitForExpect(() => expect(received).toHaveLength(1), 5000, 10)
    })

    it.each([200, 403])(
        'records the answer %s that the feedback got as a feedback record of the unit',
        async (status) => {
            answer = status
            await bounceEverySend()

            await sendTracked()

            await waitForExpect(
                async () =>
                    expect(
                        (await truth()).map(({ kind, status, fault, unitId }) => [kind, status, fault, unitId])
                    ).toEqual([
                        ['ses.send', 200, 'ses.reject', 'run-1-1'],
                        ['ses.feedback', status, 'ses.reject', 'run-1-1'],
                    ]),
                5000,
                10
            )
        }
    )
    const postEveryEvent = {
        delivery: 0.5,
        hardBounce: 0.25,
        softBounce: 0.25,
        complaint: 0.25,
        open: 0.25,
        click: 0.25,
    }

    it('posts signed delivery, bounce, complaint, open and click notifications that the SES webhook handler takes', async () => {
        expect((await control('PUT', '/_feedback', postEveryEvent)).status).toBe(204)

        for (let i = 0; i < 4; i++) {
            expect(await sendTracked()).toBe(200)
        }
        await waitForExpect(() => expect(received).toHaveLength(7), 5000, 10)
        const handled = await handleInCdpApiProcess(received.map(({ body }) => body))

        expect(handled).toEqual({ code: 0, handled: expect.any(Array) })
        expect(
            received
                .map((post, i) => ({ type: eventTypeOf(post), ...handled.handled![i] }))
                .sort((a, b) => a.type.localeCompare(b.type))
        ).toEqual([
            {
                type: 'Bounce:Permanent',
                status: 200,
                metrics: expect.arrayContaining(['email_bounced_hard']),
                hardBounced: [BOUNCED],
                softBounced: [],
                complained: [],
                delivered: [],
            },
            {
                type: 'Bounce:Transient',
                status: 200,
                metrics: expect.arrayContaining(['email_bounced_transient']),
                hardBounced: [],
                softBounced: [BOUNCED],
                complained: [],
                delivered: [],
            },
            {
                type: 'Click',
                status: 200,
                metrics: expect.arrayContaining(['email_link_clicked']),
                hardBounced: [],
                softBounced: [],
                complained: [],
                delivered: [],
            },
            {
                type: 'Complaint',
                status: 200,
                metrics: ['email_blocked'],
                hardBounced: [],
                softBounced: [],
                complained: [BOUNCED],
                delivered: [],
            },
            {
                type: 'Delivery',
                status: 200,
                metrics: ['email_delivered'],
                hardBounced: [],
                softBounced: [],
                complained: [],
                delivered: [BOUNCED],
            },
            {
                type: 'Delivery',
                status: 200,
                metrics: ['email_delivered'],
                hardBounced: [],
                softBounced: [],
                complained: [],
                delivered: [BOUNCED],
            },
            {
                type: 'Open',
                status: 200,
                metrics: ['email_opened'],
                hardBounced: [],
                softBounced: [],
                complained: [],
                delivered: [],
            },
        ])
    }, 60_000)

    it('posts each event type for its share of the sends it accepts', async () => {
        await control('PUT', '/_feedback', {
            delivery: 0.6,
            hardBounce: 0.2,
            softBounce: 0.1,
            complaint: 0.1,
            open: 0.3,
            click: 0.1,
        })

        for (let i = 0; i < 20; i++) {
            await sendTracked()
        }

        await waitForExpect(
            () =>
                expect(countsOf(received.map(eventTypeOf))).toEqual({
                    Delivery: 12,
                    'Bounce:Permanent': 4,
                    'Bounce:Transient': 2,
                    Complaint: 2,
                    Open: 6,
                    Click: 2,
                }),
            5000,
            10
        )
        const outcomesBySend = Map.groupBy(
            received.map((post) => ({
                type: eventTypeOf(post),
                messageId: (
                    parseJSON((parseJSON(post.body) as { Message: string }).Message) as { mail: { messageId: string } }
                ).mail.messageId,
            })),
            ({ messageId }) => messageId
        )
        expect(
            [...outcomesBySend.values()].filter(
                (events) => events.filter(({ type }) => type === 'Delivery' || type.startsWith('Bounce')).length > 1
            )
        ).toEqual([])
    })

    it('records each notification with its event type and the answer it got', async () => {
        answer = 503
        await control('PUT', '/_feedback', { delivery: 1 })

        await sendTracked()

        await waitForExpect(
            async () =>
                expect(
                    (await truth())
                        .filter(({ kind }) => kind === 'ses.feedback')
                        .map(({ status, fault, unitId, detail }) => ({ status, fault, unitId, ...detail.feedback }))
                ).toEqual([
                    {
                        status: 503,
                        fault: undefined,
                        unitId: 'run-1-1',
                        eventType: 'Delivery',
                        snsMessageId: expect.any(String),
                        sesMessageId: expect.any(String),
                        durationMs: expect.any(Number),
                    },
                ]),
            5000,
            10
        )
    })

    it.each<[string, () => Promise<unknown>, { configurationSet?: null }, string[]]>([
        ['a bounced send', bounceEverySend, {}, ['Bounce:Permanent']],
        ['a send after the shares are cleared', () => control('DELETE', '/_feedback'), {}, []],
        ['a send that names no configuration set', () => Promise.resolve(), { configurationSet: null }, []],
    ])('posts only what SES would publish for %s', async (_story, setUp, send, expected) => {
        const marker = 'run-1-9@www.example.com'
        await control('PUT', '/_feedback', { delivery: 1, open: 1 })
        await setUp()

        await sendTracked(send)
        await control('DELETE', '/_faults')
        await control('PUT', '/_feedback', { delivery: 1 })
        await sendTracked({ destination: { ToAddresses: [marker] } })

        const sentTo = (post: Received): string =>
            (parseJSON((parseJSON(post.body) as { Message: string }).Message) as { mail: { destination: string[] } })
                .mail.destination[0]
        await waitForExpect(
            () =>
                expect({
                    first: received.filter((post) => sentTo(post) !== marker).map(eventTypeOf),
                    marker: received.filter((post) => sentTo(post) === marker).map(eventTypeOf),
                }).toEqual({ first: expected, marker: ['Delivery'] }),
            5000,
            10
        )
    })

    it.each<[string, object, string]>([
        [
            'more outcomes than sends',
            { delivery: 0.8, hardBounce: 0.3 },
            'feedback: delivery and bounces add up to more than 1',
        ],
        ['more opens than deliveries', { delivery: 0.5, open: 0.6 }, 'feedback: open is more than delivery'],
        ['more clicks than opens', { delivery: 0.5, open: 0.2, click: 0.3 }, 'feedback: click is more than open'],
        ['an unknown event', { delivered: 1 }, expect.stringContaining('delivered') as unknown as string],
    ])('refuses shares with %s', async (_story, shares, problem) => {
        expect(await control('PUT', '/_feedback', shares)).toEqual({ status: 400, json: { problems: [problem] } })
    })
})
