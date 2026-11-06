import { createHash } from 'crypto'
import { readFileSync, statSync } from 'fs'
import { ParsedMail } from 'mailparser'
import net from 'net'
import { Counter, Histogram } from 'prom-client'
import { SMTPServer, SMTPServerAuthentication, SMTPServerOptions, SMTPServerSession } from 'smtp-server'
import { Readable } from 'stream'

import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { HealthCheckResultOk, PluginServerService } from '~/types'

import { CdpConfig } from '../config'
import { TeamLimit } from './smtp-limits'
import { SmtpPlan, parseSmtpMessage, planSends, visibleRecipients } from './smtp-message'
import { REPLIES, SmtpReply } from './smtp-replies'
import { SmtpActivity, SmtpCredential, SmtpSendApi } from './smtp-send-api'

const smtpRelayConnectionsTotal = new Counter({
    name: 'cdp_smtp_relay_connections_total',
    help: 'Connections to the SMTP relay by how the client started: tls (a TLS hello first) or plain (waited for the banner).',
    labelNames: ['mode'],
})
const smtpRelayRefusedTotal = new Counter({
    name: 'cdp_smtp_relay_refused_total',
    help: 'Connections and messages the relay refused to protect itself, by reason.',
    labelNames: ['reason'],
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
// Above this, the client has spent long enough uploading that the budget for short messages no longer applies, and
// each send is one at a time because every request body is another copy of the message in memory.
const LARGE_MESSAGE_BYTES = 1024 * 1024
const MAX_KEY_CHECKS_PER_IP = 10
const MAX_TRACKED_FAILED_LOGINS = 50_000
// Forward secrecy on every TLS 1.2 connection. TLS 1.3 suites are always forward secret and not set by this list.
const TLS_CIPHERS = [
    'ECDHE-ECDSA-AES128-GCM-SHA256',
    'ECDHE-RSA-AES128-GCM-SHA256',
    'ECDHE-ECDSA-AES256-GCM-SHA384',
    'ECDHE-RSA-AES256-GCM-SHA384',
    'ECDHE-ECDSA-CHACHA20-POLY1305',
    'ECDHE-RSA-CHACHA20-POLY1305',
].join(':')
const HOUSEKEEPING_INTERVAL_MS = 60_000
const SHUTDOWN_POLL_MS = 100
const TLS_HELLO_FIRST_BYTE = 0x16

type SessionWithKey = SMTPServerSession & { user?: unknown }

type FailedLogins = { count: number; windowEndsAt: number }

type OpenConnection = { ip: string; tlsDeadline: NodeJS.Timeout }

export class SmtpRelayService {
    private readonly listeners: net.Server[] = []
    private readonly openConnections = new Map<string, OpenConnection>()
    private readonly connectionsPerIp = new Map<string, number>()
    private readonly keyChecks = new Map<string, Promise<SmtpCredential>>()
    private readonly keyChecksPerIp = new Map<string, number>()
    private lastConnectionId = 0
    private readonly failedLogins = new Map<string, FailedLogins>()
    private readonly keyCache = new Map<string, { credential: SmtpCredential; expiresAt: number }>()
    private plainServer!: SMTPServer
    private tlsServer!: SMTPServer
    private readonly messageSlots: TeamLimit
    private readonly messageBytes: TeamLimit
    private certificateMtimeMs = 0
    private housekeepingTimer?: NodeJS.Timeout
    private readonly api: SmtpSendApi

    constructor(private readonly config: CdpConfig) {
        this.api = new SmtpSendApi(config.SMTP_RELAY_API_URL, config.SMTP_RELAY_ACTIVITY_JWT_SECRET)
        this.messageSlots = new TeamLimit(
            config.SMTP_RELAY_MAX_CONCURRENT_MESSAGES,
            config.SMTP_RELAY_MAX_CONCURRENT_MESSAGES_PER_TEAM
        )
        this.messageBytes = new TeamLimit(
            config.SMTP_RELAY_MAX_IN_FLIGHT_BYTES,
            config.SMTP_RELAY_MAX_IN_FLIGHT_BYTES_PER_TEAM
        )
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
            minVersion: 'TLSv1.2',
            ciphers: TLS_CIPHERS,
            size: this.config.SMTP_RELAY_MAX_MESSAGE_BYTES,
            authMethods: ['PLAIN', 'LOGIN'],
            hideSMTPUTF8: true,
            hideDSN: true,
            hideENHANCEDSTATUSCODES: true,
            hideREQUIRETLS: true,
            closeTimeout: this.config.SMTP_RELAY_SHUTDOWN_GRACE_MS,
            authRequiredMessage: `5.7.0 Authentication required. Use a project secret key as the password.`,
            logger: false,
            disableReverseLookup: true,
            onSecure: (_socket, session, callback) => {
                const connection = this.openConnections.get(session.id)
                if (connection) {
                    clearTimeout(connection.tlsDeadline)
                }
                callback()
            },
            onClose: (session) => this.releaseConnection(session.id),
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
        while (this.messageSlots.inUse > 0 && Date.now() < deadline) {
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
        for (const [key, failed] of this.failedLogins) {
            if (failed.windowEndsAt <= now) {
                this.failedLogins.delete(key)
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
        const id = this.admitConnection(socket)
        if (!id) {
            return
        }
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
            ;(isTls ? this.tlsServer : this.plainServer).connect(socket, { id })
        }
        const onData = (chunk: Buffer): void => settle(chunk)
        const onError = (): void => {
            socket.destroy()
        }
        const onClose = (): void => {
            settled = true
            clearTimeout(timer)
            this.releaseConnection(id)
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

    // Counted here rather than in the SMTP server's hooks, because those only run after TLS, and a socket holds its
    // place from the moment it opens. Returns the connection's ID, or null when it was refused.
    private admitConnection(socket: net.Socket): string | null {
        socket.on('error', () => socket.destroy())
        const ip = (socket.remoteAddress ?? '').replace(/^::ffff:/, '')
        const open = this.connectionsPerIp.get(ip) ?? 0
        const refusal =
            this.openConnections.size >= this.config.SMTP_RELAY_MAX_CLIENTS
                ? REPLIES.tooManyClients()
                : open >= this.config.SMTP_RELAY_MAX_CONNECTIONS_PER_IP
                  ? REPLIES.tooManyConnections()
                  : null
        if (refusal) {
            smtpRelayRefusedTotal.inc({ reason: 'connections' })
            socket.end(`${refusal.line}\r\n`, () => socket.destroy())
            return null
        }
        this.lastConnectionId += 1
        const id = String(this.lastConnectionId)
        this.connectionsPerIp.set(ip, open + 1)
        // Nothing can be sent before TLS, so a connection that hasn't finished it by now has no use for its place.
        const tlsDeadline = setTimeout(() => {
            smtpRelayRefusedTotal.inc({ reason: 'tls_deadline' })
            socket.destroy()
        }, this.config.SMTP_RELAY_TLS_DEADLINE_MS)
        tlsDeadline.unref()
        this.openConnections.set(id, { ip, tlsDeadline })
        return id
    }

    private releaseConnection(id: string): void {
        const connection = this.openConnections.get(id)
        if (!connection) {
            return
        }
        this.openConnections.delete(id)
        clearTimeout(connection.tlsDeadline)
        const open = this.connectionsPerIp.get(connection.ip) ?? 0
        if (open <= 1) {
            this.connectionsPerIp.delete(connection.ip)
        } else {
            this.connectionsPerIp.set(connection.ip, open - 1)
        }
    }

    private isLockedOut(key: string): boolean {
        const failed = this.failedLogins.get(key)
        if (!failed) {
            return false
        }
        if (failed.windowEndsAt <= Date.now()) {
            this.failedLogins.delete(key)
            return false
        }
        return failed.count >= this.config.SMTP_RELAY_MAX_FAILED_LOGINS_PER_IP
    }

    private recordFailedLogin(key: string): void {
        const failed = this.failedLogins.get(key)
        if (failed && failed.windowEndsAt > Date.now()) {
            failed.count += 1
            return
        }
        if (this.failedLogins.size >= MAX_TRACKED_FAILED_LOGINS) {
            this.failedLogins.delete(this.failedLogins.keys().next().value as string)
        }
        this.failedLogins.set(key, { count: 1, windowEndsAt: Date.now() + FAILED_LOGIN_WINDOW_MS })
    }

    // Any username is accepted: tools without a username field send the From address or the key itself.
    private async authenticate(auth: SMTPServerAuthentication, session: SMTPServerSession): Promise<SmtpCredential> {
        const ip = session.remoteAddress
        const password = auth.password ?? ''
        const cacheKey = createHash('sha256').update(password).digest('hex')
        const cached = this.keyCache.get(cacheKey)
        if (cached && cached.expiresAt > Date.now()) {
            smtpRelayAuthTotal.inc({ result: 'cached' })
            return cached.credential
        }
        // Per key, because many customers can share one address, and one customer's bad key must not lock out the rest.
        const failedLoginKey = `${ip}:${cacheKey}`
        if (this.isLockedOut(failedLoginKey)) {
            smtpRelayAuthTotal.inc({ result: 'locked_out' })
            throw REPLIES.tooManyFailedLogins()
        }
        try {
            if (!password.startsWith('phs_')) {
                throw REPLIES.invalidCredentials()
            }
            const credential = await this.checkKeyOnce(password, cacheKey, ip)
            smtpRelayAuthTotal.inc({ result: '235' })
            return credential
        } catch (error) {
            if (error instanceof SmtpReply) {
                smtpRelayAuthTotal.inc({ result: String(error.responseCode) })
                // An outage on our side must not lock anyone out.
                if (!error.isTemporary) {
                    this.recordFailedLogin(failedLoginKey)
                }
            }
            throw error
        }
    }

    // Logins that arrive together with the same key share one check, and an address can only start so many checks at
    // once, so that made-up keys can't turn into unlimited calls to Django.
    private checkKeyOnce(password: string, cacheKey: string, ip: string): Promise<SmtpCredential> {
        const running = this.keyChecks.get(cacheKey)
        if (running) {
            return running
        }
        const started = this.keyChecksPerIp.get(ip) ?? 0
        if (started >= MAX_KEY_CHECKS_PER_IP) {
            return Promise.reject(REPLIES.authUnavailable())
        }
        this.keyChecksPerIp.set(ip, started + 1)
        const check = this.api
            .checkKey(password)
            .then((credential) => {
                this.keyCache.set(cacheKey, { credential, expiresAt: Date.now() + KEY_CACHE_TTL_MS })
                return credential
            })
            .finally(() => {
                this.keyChecks.delete(cacheKey)
                const remaining = (this.keyChecksPerIp.get(ip) ?? 1) - 1
                if (remaining <= 0) {
                    this.keyChecksPerIp.delete(ip)
                } else {
                    this.keyChecksPerIp.set(ip, remaining)
                }
            })
        this.keyChecks.set(cacheKey, check)
        return check
    }

    private async handleData(stream: Readable & { sizeExceeded?: boolean }, session: SessionWithKey): Promise<string> {
        const credential = session.user as unknown as SmtpCredential
        const { teamId } = credential
        // The socket's idle timeout can't end a client that sends a byte now and then. Destroying the stream ends the
        // read below, and the SMTP server sends this reply and closes the connection.
        const dataDeadline = setTimeout(() => {
            smtpRelayRefusedTotal.inc({ reason: 'data_deadline' })
            stream.destroy(REPLIES.dataTooSlow())
        }, this.config.SMTP_RELAY_DATA_DEADLINE_MS)
        dataDeadline.unref()
        const held = { bytes: 0 }
        const hasSlot = this.messageSlots.tryTake(teamId, 1)
        try {
            const raw = await this.readOrRefuse(stream, teamId, held, hasSlot)
            clearTimeout(dataDeadline)
            return await this.deliverAndReply(raw, session, credential)
        } finally {
            clearTimeout(dataDeadline)
            this.messageBytes.give(teamId, held.bytes)
            if (hasSlot) {
                this.messageSlots.give(teamId, 1)
            }
        }
    }

    private async readOrRefuse(
        stream: Readable & { sizeExceeded?: boolean },
        teamId: number,
        held: { bytes: number },
        hasSlot: boolean
    ): Promise<Buffer> {
        try {
            if (hasSlot) {
                return await this.readMessage(stream, teamId, held)
            }
            smtpRelayRefusedTotal.inc({ reason: 'slots' })
            for await (const _chunk of stream) {
                // Only read so that the client gets its reply.
            }
            throw REPLIES.busy()
        } catch (error) {
            if (error instanceof SmtpReply) {
                this.observeReply(error, 0)
            }
            throw error
        }
    }

    private async deliverAndReply(raw: Buffer, session: SessionWithKey, credential: SmtpCredential): Promise<string> {
        const startedAt = performance.now()
        const envelope = {
            from: session.envelope.mailFrom ? session.envelope.mailFrom.address : undefined,
            to: session.envelope.rcptTo.map((recipient) => recipient.address),
        }
        let visible: string[] = []
        try {
            const parsed = await parseSmtpMessage(raw)
            visible = visibleRecipients(parsed, envelope.to)
            const reply = await this.deliver(raw.length, parsed, envelope, visible, credential)
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
                to: visible,
            })
            throw reply
        }
    }

    private async readMessage(
        stream: Readable & { sizeExceeded?: boolean },
        teamId: number,
        held: { bytes: number }
    ): Promise<Buffer> {
        let chunks: Buffer[] = []
        let received = 0
        let keeping = true
        for await (const chunk of stream) {
            received += (chunk as Buffer).length
            if (!keeping) {
                // Past a limit the rest is only read so that the client gets its reply.
                continue
            }
            if (
                received <= this.config.SMTP_RELAY_MAX_MESSAGE_BYTES &&
                this.messageBytes.tryTake(teamId, (chunk as Buffer).length)
            ) {
                held.bytes += (chunk as Buffer).length
                chunks.push(chunk as Buffer)
            } else {
                keeping = false
                chunks = []
                this.messageBytes.give(teamId, held.bytes)
                held.bytes = 0
            }
        }
        if (stream.sizeExceeded || received > this.config.SMTP_RELAY_MAX_MESSAGE_BYTES) {
            throw REPLIES.tooLarge(this.config.SMTP_RELAY_MAX_MESSAGE_BYTES)
        }
        if (!keeping) {
            smtpRelayRefusedTotal.inc({ reason: 'bytes' })
            throw REPLIES.busy()
        }
        return Buffer.concat(chunks)
    }

    private async deliver(
        rawBytes: number,
        parsed: ParsedMail,
        envelope: { from?: string; to: string[] },
        visible: string[],
        credential: SmtpCredential
    ): Promise<string> {
        const plan = planSends(parsed, envelope)
        const isLarge = rawBytes > LARGE_MESSAGE_BYTES
        const budgetMs = isLarge
            ? this.config.SMTP_RELAY_LARGE_MESSAGE_BUDGET_MS
            : this.config.SMTP_RELAY_REPLY_BUDGET_MS
        const { messageIds, refusals, temporary } = await this.sendAll(
            credential,
            plan,
            Date.now() + budgetMs,
            isLarge ? 1 : FAN_OUT_CONCURRENCY
        )

        if (plan.droppedHeaders.length > 0 && messageIds.length > 0) {
            this.recordInBackground(credential, {
                kind: 'dropped_headers',
                from: plan.fromAddress,
                to: visible,
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
        deadline: number,
        concurrency: number
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
        await Promise.all(Array.from({ length: Math.min(concurrency, plan.sends.length) }, () => worker()))
        return { messageIds, refusals, temporary }
    }

    private observeReply(refusal: SmtpReply | null, durationMs: number): void {
        const code = refusal ? refusal.responseCode : 250
        smtpRelayMessagesTotal.inc({ code: String(code) })
        smtpRelayReplyMs.observe({ class: `${Math.floor(code / 100)}xx` }, durationMs)
    }

    private recordInBackground(credential: SmtpCredential, activity: SmtpActivity): void {
        void this.api.recordActivity(credential.teamId, activity)
    }
}
