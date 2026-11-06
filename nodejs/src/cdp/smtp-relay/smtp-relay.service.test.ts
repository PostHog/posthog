import { execFileSync } from 'child_process'
import { mkdtempSync, rmSync } from 'fs'
import net from 'net'
import nodemailer from 'nodemailer'
import { tmpdir } from 'os'
import { join } from 'path'
import { TLSSocket, connect as tlsConnect } from 'tls'

import { waitForExpect } from '~/tests/helpers/expectations'

import { CdpConfig } from '../config'
import { SmtpRelayService } from './smtp-relay.service'
import { REPLIES } from './smtp-replies'
import { SmtpCredential, SmtpSendApi } from './smtp-send-api'

jest.mock('~/common/utils/posthog', () => ({ captureException: jest.fn() }))

// The relay under test uses a certificate that this test creates for itself.
// nosemgrep: problem-based-packs.insecure-transport.js-node.bypass-tls-verification.bypass-tls-verification
const TRUST_TEST_CERTIFICATE = { rejectUnauthorized: false }

describe('SmtpRelayService', () => {
    let directory: string
    let relay: SmtpRelayService
    let port: number
    let checkKey: jest.SpyInstance
    let send: jest.SpyInstance
    let recordActivity: jest.SpyInstance
    const credential: SmtpCredential = { apiKey: 'phs_good', teamId: 1 }

    const transport = (auth: { user: string; pass: string } | undefined = { user: 'posthog', pass: 'phs_good' }) =>
        nodemailer.createTransport({ host: '127.0.0.1', port, tls: TRUST_TEST_CERTIFICATE, auth })

    const firstLine = (socket: net.Socket): Promise<string> =>
        new Promise((resolve) => socket.once('data', (data) => resolve(data.toString().split('\r\n')[0])))

    beforeAll(() => {
        directory = mkdtempSync(join(tmpdir(), 'smtp-relay-test-'))
        // nosemgrep: trailofbits.generic.openssl-insecure-flags.openssl-insecure-flags
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

    const startRelay = async (overrides: Partial<CdpConfig> = {}): Promise<void> => {
        relay = new SmtpRelayService({
            SMTP_RELAY_API_URL: 'http://unused.invalid',
            SMTP_RELAY_HOSTNAME: 'localhost',
            SMTP_RELAY_MAX_MESSAGE_BYTES: 1024 * 1024,
            SMTP_RELAY_REPLY_BUDGET_MS: 4_000,
            SMTP_RELAY_LARGE_MESSAGE_BUDGET_MS: 4_000,
            SMTP_RELAY_MAX_CLIENTS: 100,
            SMTP_RELAY_MAX_CONNECTIONS_PER_IP: 100,
            SMTP_RELAY_MAX_CONCURRENT_MESSAGES: 5,
            SMTP_RELAY_MAX_CONCURRENT_MESSAGES_PER_TEAM: 5,
            SMTP_RELAY_MAX_IN_FLIGHT_BYTES: 10 * 1024 * 1024,
            SMTP_RELAY_MAX_IN_FLIGHT_BYTES_PER_TEAM: 10 * 1024 * 1024,
            SMTP_RELAY_TLS_DEADLINE_MS: 10_000,
            SMTP_RELAY_DATA_DEADLINE_MS: 10_000,
            SMTP_RELAY_ACTIVITY_JWT_SECRET: '',
            SMTP_RELAY_TLS_WAIT_IMPLICIT_MS: 50,
            SMTP_RELAY_PORTS: '0',
            SMTP_RELAY_IMPLICIT_TLS_PORTS: '',
            SMTP_RELAY_TLS_KEY_PATH: join(directory, 'tls.key'),
            SMTP_RELAY_TLS_CERT_PATH: join(directory, 'tls.crt'),
            SMTP_RELAY_TLS_WAIT_STARTTLS_MS: 50,
            SMTP_RELAY_SHUTDOWN_GRACE_MS: 500,
            SMTP_RELAY_MAX_FAILED_LOGINS_PER_IP: 2,
            ...overrides,
        } as unknown as CdpConfig)
        await relay.start()
        port = relay.listeningPorts[0]
    }

    const restartRelay = async (overrides: Partial<CdpConfig>): Promise<void> => {
        await relay.stop()
        await startRelay(overrides)
    }

    const closed = (socket: net.Socket): Promise<void> =>
        new Promise((resolve) => socket.once('close', () => resolve()))

    // Stops at DATA, so a test can decide how the message arrives.
    const openData = async (key = 'phs_good'): Promise<{ socket: TLSSocket; reply: () => Promise<string> }> => {
        const socket = tlsConnect({ port, host: '127.0.0.1', ...TRUST_TEST_CERTIFICATE })
        socket.on('error', () => undefined)
        const replies: string[] = []
        const waiting: ((line: string) => void)[] = []
        let buffered = ''
        socket.on('data', (data) => {
            buffered += data.toString()
            let end = buffered.indexOf('\r\n')
            while (end >= 0) {
                const line = buffered.slice(0, end)
                buffered = buffered.slice(end + 2)
                if (line[3] !== '-') {
                    const next = waiting.shift()
                    if (next) {
                        next(line)
                    } else {
                        replies.push(line)
                    }
                }
                end = buffered.indexOf('\r\n')
            }
        })
        const reply = (): Promise<string> =>
            replies.length > 0 ? Promise.resolve(replies.shift()!) : new Promise((resolve) => waiting.push(resolve))
        await reply()
        const login = Buffer.from(`\0posthog\0${key}`).toString('base64')
        for (const command of [
            'EHLO test',
            `AUTH PLAIN ${login}`,
            'MAIL FROM:<a@example.com>',
            'RCPT TO:<b@example.com>',
        ]) {
            socket.write(`${command}\r\n`)
            await reply()
        }
        socket.write('DATA\r\n')
        await reply()
        return { socket, reply }
    }

    beforeEach(async () => {
        checkKey = jest.spyOn(SmtpSendApi.prototype, 'checkKey').mockImplementation((key) => {
            return key === 'phs_good' ? Promise.resolve(credential) : Promise.reject(REPLIES.invalidCredentials())
        })
        send = jest.spyOn(SmtpSendApi.prototype, 'send').mockResolvedValue('message-1')
        recordActivity = jest.spyOn(SmtpSendApi.prototype, 'recordActivity').mockResolvedValue()
        await startRelay()
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
                tls: TRUST_TEST_CERTIFICATE,
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
            credential.teamId,
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

    it('leaves Bcc recipients out of what it records about a refusal', async () => {
        send.mockRejectedValue(REPLIES.noSender())

        await expect(
            transport().sendMail({ ...mail, cc: 'copy@example.com', bcc: 'hidden@example.com' })
        ).rejects.toMatchObject({ responseCode: 550 })

        expect(recordActivity.mock.calls[0][1].to.sort()).toEqual(['a@example.com', 'copy@example.com'])
    })

    it('locks out a bad key from an address, but not over an outage on our side, and not for other keys', async () => {
        checkKey.mockRejectedValueOnce(REPLIES.authUnavailable())
        await expect(transport({ user: 'posthog', pass: 'phs_bad' }).verify()).rejects.toMatchObject({
            responseCode: 454,
        })
        for (let attempt = 0; attempt < 2; attempt++) {
            await expect(transport({ user: 'posthog', pass: 'phs_bad' }).verify()).rejects.toMatchObject({
                responseCode: 535,
            })
        }

        await expect(transport({ user: 'posthog', pass: 'phs_bad' }).verify()).rejects.toMatchObject({
            responseCode: 454,
        })
        expect(checkKey).toHaveBeenCalledTimes(3)
        await expect(transport({ user: 'posthog', pass: 'phs_good' }).verify()).resolves.toBe(true)
    })

    it('lets many logins that arrive together with one new key through on a single key check', async () => {
        const verified = await Promise.all(Array.from({ length: 20 }, () => transport().verify()))

        expect(verified).toEqual(Array(20).fill(true))
        expect(checkKey).toHaveBeenCalledTimes(1)
    })

    it('counts each connection once from accept, and frees its place when it closes', async () => {
        await restartRelay({ SMTP_RELAY_MAX_CONNECTIONS_PER_IP: 2 } as Partial<CdpConfig>)
        const held = [net.connect(port, '127.0.0.1'), net.connect(port, '127.0.0.1')]
        held[0].write(Buffer.from([0x16]))
        await firstLine(held[1])

        const refused = net.connect(port, '127.0.0.1')
        expect(await firstLine(refused)).toMatch(/^421 4\.7\.0 /)
        await closed(refused)

        const stillRefused = net.connect(port, '127.0.0.1')
        expect(await firstLine(stillRefused)).toMatch(/^421 4\.7\.0 /)
        await closed(stillRefused)

        held[0].destroy()
        // The relay frees the place when it sees the close, which is after this side sees it.
        await waitForExpect(async () => {
            const next = net.connect(port, '127.0.0.1')
            const line = await firstLine(next)
            next.destroy()
            expect(line).toMatch(/^220 /)
        })
        held[1].destroy()
    })

    it.each([
        ['stops at a TLS hello', (socket: net.Socket) => socket.write(Buffer.from([0x16]))],
        ['never starts TLS', (_socket: net.Socket) => undefined],
    ])('closes a connection that %s before the TLS deadline passes', async (_name, start) => {
        await restartRelay({ SMTP_RELAY_TLS_DEADLINE_MS: 200 } as Partial<CdpConfig>)
        const socket = net.connect(port, '127.0.0.1')
        socket.on('error', () => undefined)
        socket.on('data', () => undefined)
        start(socket)

        await closed(socket)

        await expect(transport().verify()).resolves.toBe(true)
    })

    it('refuses a team over its message slots, while another team still sends', async () => {
        await restartRelay({ SMTP_RELAY_MAX_CONCURRENT_MESSAGES_PER_TEAM: 1 } as Partial<CdpConfig>)
        checkKey.mockImplementation((key) => Promise.resolve({ apiKey: key, teamId: key === 'phs_other' ? 2 : 1 }))
        const slow = await openData()

        const refused = await openData()
        refused.socket.write('Subject: x\r\n\r\nx\r\n.\r\n')
        expect(await refused.reply()).toMatch(/^451 4\.3\.2 /)

        const other = await openData('phs_other')
        other.socket.write('From: a@example.com\r\nTo: b@example.com\r\n\r\nx\r\n.\r\n')
        expect(await other.reply()).toMatch(/^250 /)
        for (const { socket } of [slow, refused, other]) {
            socket.destroy()
        }
    })

    it('answers a message over the byte limit with a retry, and frees its bytes', async () => {
        await restartRelay({ SMTP_RELAY_MAX_IN_FLIGHT_BYTES_PER_TEAM: 2048 } as Partial<CdpConfig>)
        const large = await openData()
        large.socket.write(`From: a@example.com\r\nTo: b@example.com\r\n\r\n${'x'.repeat(4096)}\r\n.\r\n`)
        expect(await large.reply()).toMatch(/^451 4\.3\.2 /)
        expect(send).not.toHaveBeenCalled()

        large.socket.write('RSET\r\n')
        await large.reply()
        await expect(transport().sendMail(mail)).resolves.toMatchObject({ response: expect.stringContaining('250') })
        large.socket.destroy()
    })

    it('ends a message that is still arriving at the deadline, and frees its slot', async () => {
        await restartRelay({
            SMTP_RELAY_MAX_CONCURRENT_MESSAGES_PER_TEAM: 1,
            SMTP_RELAY_DATA_DEADLINE_MS: 200,
        } as Partial<CdpConfig>)
        const slow = await openData()
        slow.socket.write('Subject: x\r\n')

        expect(await slow.reply()).toMatch(/^421 4\.4\.2 /)

        await expect(transport().sendMail(mail)).resolves.toMatchObject({ response: expect.stringContaining('250') })
        slow.socket.destroy()
    })

    it('sends a large message to one recipient at a time', async () => {
        await restartRelay({ SMTP_RELAY_MAX_MESSAGE_BYTES: 3 * 1024 * 1024 } as Partial<CdpConfig>)
        let inFlight = 0
        let mostInFlight = 0
        send.mockImplementation(async () => {
            inFlight += 1
            mostInFlight = Math.max(mostInFlight, inFlight)
            await new Promise((resolve) => setImmediate(resolve))
            inFlight -= 1
            return 'id'
        })

        await transport().sendMail({
            ...mail,
            to: 'a@example.com, b@example.com, c@example.com',
            text: 'x'.repeat(2 * 1024 * 1024),
        })

        expect(send).toHaveBeenCalledTimes(3)
        expect(mostInFlight).toEqual(1)
    })

    it('refuses a message over the limit whatever SIZE it declared', async () => {
        await expect(
            transport().sendMail({ ...mail, envelope: undefined, text: 'x'.repeat(1024 * 1024 + 10) })
        ).rejects.toMatchObject({ responseCode: 552 })
        expect(send).not.toHaveBeenCalled()
    })

    it('tells an open connection to reconnect when it shuts down', async () => {
        const socket = tlsConnect({ port, host: '127.0.0.1', ...TRUST_TEST_CERTIFICATE })
        await firstLine(socket)
        const goodbye = firstLine(socket)

        await relay.stop()

        expect(await goodbye).toMatch(/^421 4\.3\.2 /)
        socket.destroy()
    })
})
