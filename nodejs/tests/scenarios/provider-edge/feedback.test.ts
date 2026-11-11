import { ProviderEdge, TruthRecord, startProviderEdge } from '.'
import { mkdtempSync, readFileSync, rmSync } from 'fs'
import http from 'http'
import { AddressInfo } from 'net'
import os from 'os'
import path from 'path'
// eslint-disable-next-line no-restricted-imports
import { ProxyAgent, request } from 'undici'

import { SesWebhookHandler } from '~/cdp/services/messaging/helpers/ses'
import { EmailTrackingCodeSigner } from '~/cdp/services/messaging/helpers/tracking-code'
import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'
import { waitForExpect } from '~/tests/helpers/expectations'

const TRACKING_KEYS = 'scenario-tracking-key'
const BOUNCED = 'run-1-1@www.example.com'

type Received = { contentType: string | undefined; body: string }

describe('provider edge SES feedback', () => {
    let caDir: string
    let receiver: http.Server
    let received: Received[]
    let answer: number
    let edge: ProviderEdge
    let client: ProxyAgent
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
        })
        client = new ProxyAgent({
            uri: edge.url,
            proxyTunnel: true,
            requestTls: { ca: readFileSync(edge.caCertPath!) },
        })
    })

    afterEach(async () => {
        await client.close()
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

    const sendTracked = async (): Promise<number> =>
        (
            await control('POST', '/v2/email/outbound-emails', {
                FromEmailAddress: 'flows@www.example.com',
                Destination: { ToAddresses: [BOUNCED] },
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
                ConfigurationSetName: 'scenario-tracking',
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

    it('answers a bounced send, then posts a signed hard bounce that the SES webhook handler verifies and suppresses', async () => {
        await bounceEverySend()

        expect(await sendTracked()).toBe(200)
        await waitForExpect(() => expect(received).toHaveLength(1), 5000, 10)

        const envelope = parseJSON(received[0].body) as { SigningCertURL: string }
        const certificate = await request(envelope.SigningCertURL, { dispatcher: client })
        expect(certificate.statusCode).toBe(200)
        const handler = new SesWebhookHandler(signer)
        handler.certCache[envelope.SigningCertURL] = certificate.body.text()

        expect(await handler.verifyDelivery(envelope)).toEqual({
            envelope: expect.objectContaining({ Type: 'Notification' }),
        })
        expect((await handler.handleWebhook({ body: envelope, verifySignature: true })).hardBounceRecipients).toEqual([
            expect.objectContaining({ teamId: '7', emailAddresses: [BOUNCED] }),
        ])
        expect(received[0].contentType).toMatch(/^text\/plain/)
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
