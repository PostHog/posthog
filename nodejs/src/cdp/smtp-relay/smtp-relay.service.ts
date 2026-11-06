import { createHash } from 'crypto'
import { readFileSync, statSync } from 'fs'
import net from 'net'
import { Counter, Histogram } from 'prom-client'
import { SMTPServer, SMTPServerAuthentication, SMTPServerOptions, SMTPServerSession } from 'smtp-server'
import { Readable } from 'stream'

import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { HealthCheckResultOk, PluginServerService } from '~/types'

import { CdpConfig } from '../config'
import { SmtpPlan, parseSmtpMessage, planSends } from './smtp-message'
import { REPLIES, SmtpReply } from './smtp-replies'
import { SmtpActivity, SmtpCredential, SmtpSendApi } from './smtp-send-api'

const smtpRelayConnectionsTotal = new Counter({
    name: 'cdp_smtp_relay_connections_total',
    help: 'Connections to the SMTP relay by how the client started: tls (a TLS hello first) or plain (waited for the banner).',
    labelNames: ['mode'],
})
const smtpRelayAuthTotal = new Counter({
    name: 'cdp_smtp_relay_auth_total',
    help: 'SMTP logins by the reply code the client got, with cached for a login answered from the key cache.',
    labelNames: ['result'],
})
const smtpRelayMessagesTotal = new Counter({
    name: 'cdp_smtp_relay_messages_total',
    help: 'Messages through DATA by the reply code the client got.',
    labelNames: ['code'],
})
const smtpRelayReplyMs = new Histogram({
    name: 'cdp_smtp_relay_reply_ms',
    help: 'Milliseconds from the end of DATA to the reply, by the reply class. A client that sends with short timeouts gives up after 5 seconds.',
    labelNames: ['class'],
    buckets: [50, 100, 250, 500, 1_000, 2_000, 3_000, 4_000, 5_000, 10_000, 20_000],
})

const KEY_CACHE_TTL_MS = 60_000
const FAILED_LOGIN_WINDOW_MS = 5 * 60_000
const FAN_OUT_CONCURRENCY = 5
// Above this, the client has spent long enough uploading that the budget for short messages no longer applies.
const LARGE_MESSAGE_BYTES = 1024 * 1024
const HOUSEKEEPING_INTERVAL_MS = 60_000
const SHUTDOWN_POLL_MS = 100
const TLS_HELLO_FIRST_BYTE = 0x16

type SessionWithKey = SMTPServerSession & { user?: unknown }

type FailedLogins = { count: number; windowEndsAt: number }

export class SmtpRelayService {
    private readonly listeners: net.Server[] = []
    private readonly connectionsPerIp = new Map<string, number>()
    private readonly failedLogins = new Map<string, FailedLogins>()
    private readonly keyCache = new Map<string, { credential: SmtpCredential; expiresAt: number }>()
    private plainServer!: SMTPServer
    private tlsServer!: SMTPServer
    private activeMessages = 0
    private certificateMtimeMs = 0
    private housekeepingTimer?: NodeJS.Timeout
    private readonly api: SmtpSendApi

    constructor(private readonly config: CdpConfig) {
        this.api = new SmtpSendApi(config.SMTP_RELAY_API_URL)
    }

    public get service(): PluginServerService {
        return {
            id: 'cdp-smtp-relay',
            onShutdown: () => this.stop(),
            healthcheck: () => new HealthCheckResultOk(),
        }
    }

    public async start(): Promise<void> {
        const certificate = this.readCertificate()
        const options: SMTPServerOptions = {
            name: this.config.SMTP_RELAY_HOSTNAME,
            banner: 'PostHog',
            ...certificate,
            size: this.config.SMTP_RELAY_MAX_MESSAGE_BYTES,
            authMethods: ['PLAIN', 'LOGIN'],
            hideSMTPUTF8: true,
            hideDSN: true,
            hideENHANCEDSTATUSCODES: true,
            hideREQUIRETLS: true,
            maxClients: this.config.SMTP_RELAY_MAX_CLIENTS,
            closeTimeout: this.config.SMTP_RELAY_SHUTDOWN_GRACE_MS,
            authRequiredMessage: `5.7.0 Authentication required. Use a project secret key as the password.`,
            logger: false,
            disableReverseLookup: true,
            onConnect: (session, callback) => {
                const refusal = this.refuseConnection(session.remoteAddress)
                return refusal ? callback(refusal) : callback()
            },
            onClose: (session) => this.releaseConnection(session.remoteAddress),
            onAuth: (auth, session, callback) => {
                this.authenticate(auth, session).then(
                    (credential) => callback(null, { user: credential as unknown as string }),
                    (error) => callback(error instanceof Error ? error : REPLIES.authUnavailable())
                )
            },
            onData: (stream, session, callback) => {
                this.handleData(stream, session).then(
                    (reply) => callback(null, reply),
                    (error) => callback(error instanceof Error ? error : REPLIES.unconfirmed())
                )
            },
        }
        this.plainServer = this.buildServer({ ...options, secure: false })
        this.tlsServer = this.buildServer({ ...options, secure: true, needsUpgrade: true })

        await Promise.all(
            this.config.SMTP_RELAY_PORTS.split(',')
                .map((port) => parseInt(port.trim()))
                .filter((port) => !isNaN(port))
                .map((port) => this.listen(port))
        )
        this.housekeepingTimer = setInterval(() => this.runHousekeeping(), HOUSEKEEPING_INTERVAL_MS)
        this.housekeepingTimer.unref()
    }

    public get listeningPorts(): number[] {
        return this.listeners.map((listener) => (listener.address() as net.AddressInfo).port)
    }

    // SMTPServer.close() can't drain these servers, because connections reach them through our own listeners.
    public async stop(): Promise<void> {
        clearInterval(this.housekeepingTimer)
        // A listener's close only finishes once its connections have ended, which happens below.
        const closed = Promise.all(this.listeners.map((listener) => new Promise((resolve) => listener.close(resolve))))
        const deadline = Date.now() + this.config.SMTP_RELAY_SHUTDOWN_GRACE_MS
        while (this.activeMessages > 0 && Date.now() < deadline) {
            await new Promise((resolve) => setTimeout(resolve, SHUTDOWN_POLL_MS))
        }
        for (const server of [this.plainServer, this.tlsServer]) {
            for (const connection of server.connections) {
                connection.send(421, '4.3.2 Restarting. Reconnect and retry.')
                connection.close()
            }
        }
        await closed
    }

    private runHousekeeping(): void {
        this.reloadCertificate()
        const now = Date.now()
        for (const [ip, failed] of this.failedLogins) {
            if (failed.windowEndsAt <= now) {
                this.failedLogins.delete(ip)
            }
        }
        for (const [key, cached] of this.keyCache) {
            if (cached.expiresAt <= now) {
                this.keyCache.delete(key)
            }
        }
    }

    private buildServer(options: SMTPServerOptions): SMTPServer {
        const server = new SMTPServer(options)
        // A client that drops mid-handshake or sends garbage is routine on a public port, and carries no action.
        server.on('error', (error) => logger.debug('SMTP relay connection error', { error: error.message }))
        return server
    }

    private listen(port: number): Promise<void> {
        const listener = net.createServer((socket) => this.accept(socket, port))
        this.listeners.push(listener)
        return new Promise((resolve, reject) => {
            listener.once('error', reject)
            listener.listen(port, () => {
                listener.off('error', reject)
                logger.info('📬', 'SMTP relay listening', { port })
                resolve()
            })
        })
    }

    // Any port takes either kind of client, because a TLS and port mismatch is a common way for SMTP setup to fail. A
    // client that opens with TLS sends its hello at once, and a plain one waits for the banner. A port people expect
    // TLS on waits longer, so a slow TLS client is less likely to get a plain banner.
    private accept(socket: net.Socket, port: number): void {
        const waitMs = this.implicitTlsPorts.has(port)
            ? this.config.SMTP_RELAY_TLS_WAIT_IMPLICIT_MS
            : this.config.SMTP_RELAY_TLS_WAIT_STARTTLS_MS
        let settled = false
        const settle = (first: Buffer | null): void => {
            if (settled) {
                return
            }
            settled = true
            clearTimeout(timer)
            socket.pause()
            socket.removeListener('data', onData)
            socket.removeListener('error', onError)
            socket.removeListener('close', onClose)
            if (first) {
                socket.unshift(first)
            }
            const isTls = first?.[0] === TLS_HELLO_FIRST_BYTE
            smtpRelayConnectionsTotal.inc({ mode: isTls ? 'tls' : 'plain' })
            ;(isTls ? this.tlsServer : this.plainServer).connect(socket)
        }
        const onData = (chunk: Buffer): void => settle(chunk)
        const onError = (): void => {
            socket.destroy()
        }
        const onClose = (): void => {
            settled = true
            clearTimeout(timer)
        }
        const timer = setTimeout(() => settle(null), waitMs)
        socket.on('data', onData)
        socket.on('error', onError)
        socket.on('close', onClose)
    }

    private get implicitTlsPorts(): Set<number> {
        return new Set(
            this.config.SMTP_RELAY_IMPLICIT_TLS_PORTS.split(',')
                .map((port) => parseInt(port.trim()))
                .filter((port) => !isNaN(port))
        )
    }

    private readCertificate(): { key: Buffer; cert: Buffer } {
        const { SMTP_RELAY_TLS_KEY_PATH: keyPath, SMTP_RELAY_TLS_CERT_PATH: certPath } = this.config
        if (!keyPath || !certPath) {
            throw new Error('The SMTP relay needs SMTP_RELAY_TLS_KEY_PATH and SMTP_RELAY_TLS_CERT_PATH')
        }
        this.certificateMtimeMs = statSync(certPath).mtimeMs
        return { key: readFileSync(keyPath), cert: readFileSync(certPath) }
    }

    private reloadCertificate(): void {
        try {
            if (statSync(this.config.SMTP_RELAY_TLS_CERT_PATH).mtimeMs === this.certificateMtimeMs) {
                return
            }
            const certificate = this.readCertificate()
            this.plainServer.updateSecureContext(certificate)
            this.tlsServer.updateSecureContext(certificate)
            logger.info('📬', 'SMTP relay reloaded its certificate')
        } catch (error) {
            logger.error('⚠️', 'SMTP relay could not reload its certificate', { error: String(error) })
            captureException(error)
        }
    }

    private refuseConnection(ip: string): SmtpReply | null | undefined {
        const open = this.connectionsPerIp.get(ip) ?? 0
        if (open >= this.config.SMTP_RELAY_MAX_CONNECTIONS_PER_IP) {
            return REPLIES.tooManyConnections()
        }
        this.connectionsPerIp.set(ip, open + 1)
        return undefined
    }

    private releaseConnection(ip: string): void {
        const open = this.connectionsPerIp.get(ip) ?? 0
        if (open <= 1) {
            this.connectionsPerIp.delete(ip)
        } else {
            this.connectionsPerIp.set(ip, open - 1)
        }
    }

    private isLockedOut(ip: string): boolean {
        const failed = this.failedLogins.get(ip)
        if (!failed) {
            return false
        }
        if (failed.windowEndsAt <= Date.now()) {
            this.failedLogins.delete(ip)
            return false
        }
        return failed.count >= this.config.SMTP_RELAY_MAX_FAILED_LOGINS_PER_IP
    }

    private recordFailedLogin(ip: string): void {
        const failed = this.failedLogins.get(ip)
        if (failed && failed.windowEndsAt > Date.now()) {
            failed.count += 1
        } else {
            this.failedLogins.set(ip, { count: 1, windowEndsAt: Date.now() + FAILED_LOGIN_WINDOW_MS })
        }
    }

    // Any username is accepted: tools without a username field send the From address or the key itself.
    private async authenticate(auth: SMTPServerAuthentication, session: SMTPServerSession): Promise<SmtpCredential> {
        const ip = session.remoteAddress
        if (this.isLockedOut(ip)) {
            smtpRelayAuthTotal.inc({ result: 'locked_out' })
            throw REPLIES.tooManyFailedLogins()
        }
        const password = auth.password ?? ''
        const cacheKey = createHash('sha256').update(password).digest('hex')
        const cached = this.keyCache.get(cacheKey)
        if (cached && cached.expiresAt > Date.now()) {
            smtpRelayAuthTotal.inc({ result: 'cached' })
            return cached.credential
        }
        try {
            if (!password.startsWith('phs_')) {
                throw REPLIES.invalidCredentials()
            }
            const credential = await this.api.checkKey(password)
            this.keyCache.set(cacheKey, { credential, expiresAt: Date.now() + KEY_CACHE_TTL_MS })
            smtpRelayAuthTotal.inc({ result: '235' })
            return credential
        } catch (error) {
            if (error instanceof SmtpReply) {
                smtpRelayAuthTotal.inc({ result: String(error.responseCode) })
                // An outage on our side must not lock anyone out.
                if (!error.isTemporary) {
                    this.recordFailedLogin(ip)
                }
            }
            throw error
        }
    }

    private async handleData(stream: Readable & { sizeExceeded?: boolean }, session: SessionWithKey): Promise<string> {
        if (this.activeMessages >= this.config.SMTP_RELAY_MAX_CONCURRENT_MESSAGES) {
            stream.resume()
            await new Promise((resolve) => stream.once('end', resolve))
            this.observeReply(REPLIES.busy(), 0)
            throw REPLIES.busy()
        }
        this.activeMessages += 1
        try {
            const raw = await this.readMessage(stream)
            const startedAt = performance.now()
            const credential = session.user as unknown as SmtpCredential
            const envelope = {
                from: session.envelope.mailFrom ? session.envelope.mailFrom.address : undefined,
                to: session.envelope.rcptTo.map((recipient) => recipient.address),
            }
            try {
                const reply = await this.deliver(raw, envelope, credential)
                this.observeReply(null, performance.now() - startedAt)
                return reply
            } catch (error) {
                const reply = error instanceof SmtpReply ? error : REPLIES.unconfirmed()
                if (!(error instanceof SmtpReply)) {
                    captureException(error)
                }
                this.observeReply(reply, performance.now() - startedAt)
                this.recordInBackground(credential, {
                    kind: 'refused',
                    reply: reply.line,
                    from: envelope.from,
                    to: envelope.to.slice(0, 20),
                })
                throw reply
            }
        } finally {
            this.activeMessages -= 1
        }
    }

    private async readMessage(stream: Readable & { sizeExceeded?: boolean }): Promise<Buffer> {
        const chunks: Buffer[] = []
        let received = 0
        for await (const chunk of stream) {
            // Past the limit the rest is only read so the client gets its reply.
            if (received <= this.config.SMTP_RELAY_MAX_MESSAGE_BYTES) {
                chunks.push(chunk as Buffer)
            }
            received += (chunk as Buffer).length
        }
        if (stream.sizeExceeded || received > this.config.SMTP_RELAY_MAX_MESSAGE_BYTES) {
            throw REPLIES.tooLarge(this.config.SMTP_RELAY_MAX_MESSAGE_BYTES)
        }
        return Buffer.concat(chunks)
    }

    private async deliver(
        raw: Buffer,
        envelope: { from?: string; to: string[] },
        credential: SmtpCredential
    ): Promise<string> {
        const parsed = await parseSmtpMessage(raw)
        const plan = planSends(parsed, envelope)
        const budgetMs =
            raw.length > LARGE_MESSAGE_BYTES
                ? this.config.SMTP_RELAY_LARGE_MESSAGE_BUDGET_MS
                : this.config.SMTP_RELAY_REPLY_BUDGET_MS
        const { messageIds, refusals, temporary } = await this.sendAll(credential, plan, Date.now() + budgetMs)

        if (plan.droppedHeaders.length > 0 && messageIds.length > 0) {
            this.recordInBackground(credential, {
                kind: 'dropped_headers',
                from: plan.fromAddress,
                to: envelope.to.slice(0, 20),
                message_id: messageIds[0],
                dropped_headers: plan.droppedHeaders.slice(0, 20),
            })
        }
        // Every queued recipient is safe to retry when a key exists, and a whole-message reply is all SMTP clients
        // handle well: a partial refusal is treated as success by Django and Nodemailer.
        if (refusals.length === plan.sends.length) {
            throw refusals[0]
        }
        if (temporary.length > 0) {
            if (messageIds.length > 0) {
                throw REPLIES.someUnconfirmed(messageIds.length, plan.sends.length)
            }
            throw temporary[0]
        }
        for (const refusal of refusals) {
            this.recordInBackground(credential, { kind: 'refused', reply: refusal.line, from: plan.fromAddress })
        }
        return `2.0.0 Ok: queued as ${messageIds.join(',')}`
    }

    private async sendAll(
        credential: SmtpCredential,
        plan: SmtpPlan,
        deadline: number
    ): Promise<{ messageIds: string[]; refusals: SmtpReply[]; temporary: SmtpReply[] }> {
        const messageIds: string[] = []
        const refusals: SmtpReply[] = []
        const temporary: SmtpReply[] = []
        const queue = [...plan.sends]
        const worker = async (): Promise<void> => {
            for (let send = queue.shift(); send; send = queue.shift()) {
                const remainingMs = deadline - Date.now()
                if (remainingMs <= 0) {
                    temporary.push(REPLIES.unconfirmed())
                    continue
                }
                try {
                    messageIds.push(await this.api.send(credential, send, remainingMs))
                } catch (error) {
                    const reply = error instanceof SmtpReply ? error : REPLIES.unconfirmed()
                    ;(reply.isTemporary ? temporary : refusals).push(reply)
                }
            }
        }
        await Promise.all(Array.from({ length: Math.min(FAN_OUT_CONCURRENCY, plan.sends.length) }, () => worker()))
        return { messageIds, refusals, temporary }
    }

    private observeReply(refusal: SmtpReply | null, durationMs: number): void {
        const code = refusal ? refusal.responseCode : 250
        smtpRelayMessagesTotal.inc({ code: String(code) })
        smtpRelayReplyMs.observe({ class: `${Math.floor(code / 100)}xx` }, durationMs)
    }

    private recordInBackground(credential: SmtpCredential, activity: SmtpActivity): void {
        void this.api.recordActivity(credential, activity)
    }
}
