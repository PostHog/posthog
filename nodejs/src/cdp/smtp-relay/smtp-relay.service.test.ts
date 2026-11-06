import { execFileSync } from 'child_process'
import { mkdtempSync, rmSync } from 'fs'
import net from 'net'
import nodemailer from 'nodemailer'
import { tmpdir } from 'os'
import { join } from 'path'
import { connect as tlsConnect } from 'tls'

import { CdpConfig } from '../config'
import { SmtpRelayService } from './smtp-relay.service'
import { REPLIES } from './smtp-replies'
import { SmtpCredential, SmtpSendApi } from './smtp-send-api'

jest.mock('~/common/utils/posthog', () => ({ captureException: jest.fn() }))

describe('SmtpRelayService', () => {
    let directory: string
    let relay: SmtpRelayService
    let port: number
    let checkKey: jest.SpyInstance
    let send: jest.SpyInstance
    let recordActivity: jest.SpyInstance
    const credential: SmtpCredential = { apiKey: 'phs_good', teamId: 1 }

    const transport = (auth: { user: string; pass: string } | undefined = { user: 'posthog', pass: 'phs_good' }) =>
        nodemailer.createTransport({ host: '127.0.0.1', port, tls: { rejectUnauthorized: false }, auth })

    const firstLine = (socket: net.Socket): Promise<string> =>
        new Promise((resolve) => socket.once('data', (data) => resolve(data.toString().split('\r\n')[0])))

    beforeAll(() => {
        directory = mkdtempSync(join(tmpdir(), 'smtp-relay-test-'))
        execFileSync(
            'openssl',
            ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=localhost'].concat([
                '-keyout',
                join(directory, 'tls.key'),
                '-out',
                join(directory, 'tls.crt'),
            ]),
            { stdio: 'ignore' }
        )
    })

    afterAll(() => {
        rmSync(directory, { recursive: true, force: true })
    })

    beforeEach(async () => {
        checkKey = jest.spyOn(SmtpSendApi.prototype, 'checkKey').mockImplementation((key) => {
            return key === 'phs_good' ? Promise.resolve(credential) : Promise.reject(REPLIES.invalidCredentials())
        })
        send = jest.spyOn(SmtpSendApi.prototype, 'send').mockResolvedValue('message-1')
        recordActivity = jest.spyOn(SmtpSendApi.prototype, 'recordActivity').mockResolvedValue()
        relay = new SmtpRelayService({
            SMTP_RELAY_API_URL: 'http://unused.invalid',
            SMTP_RELAY_HOSTNAME: 'localhost',
            SMTP_RELAY_MAX_MESSAGE_BYTES: 1024 * 1024,
            SMTP_RELAY_REPLY_BUDGET_MS: 4_000,
            SMTP_RELAY_LARGE_MESSAGE_BUDGET_MS: 4_000,
            SMTP_RELAY_MAX_CLIENTS: 100,
            SMTP_RELAY_MAX_CONNECTIONS_PER_IP: 100,
            SMTP_RELAY_MAX_CONCURRENT_MESSAGES: 5,
            SMTP_RELAY_TLS_WAIT_IMPLICIT_MS: 50,
            SMTP_RELAY_PORTS: '0',
            SMTP_RELAY_IMPLICIT_TLS_PORTS: '',
            SMTP_RELAY_TLS_KEY_PATH: join(directory, 'tls.key'),
            SMTP_RELAY_TLS_CERT_PATH: join(directory, 'tls.crt'),
            SMTP_RELAY_TLS_WAIT_STARTTLS_MS: 50,
            SMTP_RELAY_SHUTDOWN_GRACE_MS: 500,
            SMTP_RELAY_MAX_FAILED_LOGINS_PER_IP: 2,
        } as unknown as CdpConfig)
        await relay.start()
        port = relay.listeningPorts[0]
    })

    afterEach(async () => {
        await relay.stop()
        jest.restoreAllMocks()
    })

    const mail = { from: 'Jane <jane@example.com>', to: 'a@example.com', subject: 'Hi', text: 'Hello' }

    it('takes a client that starts with STARTTLS and hands the message to the send API', async () => {
        const info = await transport().sendMail(mail)

        expect(info.response).toEqual('250 2.0.0 Ok: queued as message-1')
        expect(send.mock.calls[0][1].body).toMatchObject({ to: 'a@example.com', from: '"Jane" <jane@example.com>' })
    })

    it('takes a client that starts with TLS on the same port', async () => {
        const info = await nodemailer
            .createTransport({
                host: '127.0.0.1',
                port,
                secure: true,
                tls: { rejectUnauthorized: false },
                auth: { user: 'anything', pass: 'phs_good' },
            })
            .sendMail(mail)

        expect(info.response).toContain('250 2.0.0')
    })

    it('refuses a login before TLS, and offers only logins it can check', async () => {
        const socket = net.connect(port, '127.0.0.1')
        await firstLine(socket)

        socket.write('EHLO test\r\n')
        const capabilities = await new Promise<string>((resolve) =>
            socket.once('data', (data) => resolve(String(data)))
        )
        socket.write('AUTH PLAIN AHBvc3Rob2cAcGhzX2dvb2Q=\r\n')
        const reply = await firstLine(socket)
        socket.destroy()

        expect(capabilities).toContain('AUTH PLAIN LOGIN\r\n')
        expect(capabilities).not.toContain('SMTPUTF8')
        expect(capabilities).not.toContain('DSN')
        expect(reply).toMatch(/^538 /)
        expect(checkKey).not.toHaveBeenCalled()
    })

    it('answers the whole message with the refusal when every send is refused', async () => {
        send.mockRejectedValue(REPLIES.noSender())

        await expect(transport().sendMail(mail)).rejects.toMatchObject({ responseCode: 550 })
        expect(recordActivity).toHaveBeenCalledWith(
            credential,
            expect.objectContaining({ kind: 'refused', reply: expect.stringContaining('550') })
        )
    })

    it.each([
        ['accepts when some recipients are refused', [REPLIES.noSender(), 'id-2'], 250],
        ['asks for a retry when a send has no answer, so nobody is lost', [REPLIES.unconfirmed(), 'id-2'], 451],
    ])('%s', async (_name, outcomes, code) => {
        for (const outcome of outcomes) {
            if (typeof outcome === 'string') {
                send.mockResolvedValueOnce(outcome)
            } else {
                send.mockRejectedValueOnce(outcome)
            }
        }

        const sending = transport().sendMail({ ...mail, to: 'a@example.com, b@example.com' })

        if (code === 250) {
            await expect(sending).resolves.toMatchObject({ response: expect.stringContaining('250 2.0.0') })
        } else {
            await expect(sending).rejects.toMatchObject({ responseCode: code })
        }
    })

    it('locks out an address after repeated bad logins, but not over an outage on our side', async () => {
        checkKey.mockRejectedValueOnce(REPLIES.authUnavailable())
        await expect(transport({ user: 'posthog', pass: 'phs_bad' }).verify()).rejects.toMatchObject({
            responseCode: 454,
        })
        for (let attempt = 0; attempt < 2; attempt++) {
            await expect(transport({ user: 'posthog', pass: 'phs_bad' }).verify()).rejects.toMatchObject({
                responseCode: 535,
            })
        }

        await expect(transport({ user: 'posthog', pass: 'phs_good' }).verify()).rejects.toMatchObject({
            responseCode: 421,
        })
    })

    it('refuses a message over the limit whatever SIZE it declared', async () => {
        await expect(
            transport().sendMail({ ...mail, envelope: undefined, text: 'x'.repeat(1024 * 1024 + 10) })
        ).rejects.toMatchObject({ responseCode: 552 })
        expect(send).not.toHaveBeenCalled()
    })

    it('tells an open connection to reconnect when it shuts down', async () => {
        const socket = tlsConnect({ port, host: '127.0.0.1', rejectUnauthorized: false })
        await firstLine(socket)
        const goodbye = firstLine(socket)

        await relay.stop()

        expect(await goodbye).toMatch(/^421 4\.3\.2 /)
        socket.destroy()
    })
})
