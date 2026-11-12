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

    const handleInCdpApiProcess = (envelope: string): Promise<{ code: number | string; stdout: string }> => {
        const script = `
            const { SesWebhookHandler } = require(${JSON.stringify(path.join(NODEJS, 'src/cdp/services/messaging/helpers/ses'))})
            const { EmailTrackingCodeSigner } = require(${JSON.stringify(path.join(NODEJS, 'src/cdp/services/messaging/helpers/tracking-code'))})
            const handler = new SesWebhookHandler(new EmailTrackingCodeSigner(${JSON.stringify(TRACKING_KEYS)}, 'https://track.example.com'))
            handler.handleWebhook({ body: JSON.parse(process.env.SNS_ENVELOPE), verifySignature: true }).then(
                (result) => process.stdout.write(JSON.stringify(result.hardBounceRecipients ?? null)),
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
                        SNS_ENVELOPE: envelope,
                        HTTPS_PROXY: edge.url,
                        NODE_EXTRA_CA_CERTS: edge.caCertPath,
                    },
                },
                (error, stdout) => resolve({ code: error ? (error.code ?? String(error.signal)) : 0, stdout })
            )
        )
    }

    it('posts a signed hard bounce that the SES webhook handler verifies through its own certificate fetch and suppresses', async () => {
        await bounceEverySend()

        expect(await sendTracked()).toBe(200)
        await waitForExpect(() => expect(received).toHaveLength(1), 5000, 10)
        const handled = await handleInCdpApiProcess(received[0].body)

        expect({
            contentType: received[0].contentType,
            code: handled.code,
            handlerError: handled.stdout.startsWith('error: ') ? handled.stdout : undefined,
        }).toEqual({ contentType: expect.stringMatching(/^text\/plain/), code: 0, handlerError: undefined })
        expect(parseJSON(handled.stdout)).toEqual([expect.objectContaining({ teamId: '7', emailAddresses: [BOUNCED] })])
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
        try {
            for (const fault of order === 'throttle first' ? [throttle, bounce] : [bounce, throttle]) {
                await control('POST', '/_faults', fault)
            }

            expect([await sendTracked(), await sendTracked()]).toEqual([200, 429])
        } finally {
            clock.mockRestore()
        }
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
})
