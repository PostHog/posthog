import nodemailer, { Transporter } from 'nodemailer'
import SMTPPool from 'nodemailer/lib/smtp-pool'

import { IntegrationType } from '~/cdp/types'
import { logger } from '~/common/utils/logger'
import { httpStaticLookup } from '~/common/utils/request'
import { registerShutdownHandler } from '~/lifecycle'

// Only submission ports — must stay in sync with ALLOWED_SMTP_PORTS in
// products/workflows/backend/providers/smtp.py. Port 25 stays blocked: unauthenticated
// relay from cloud IPs is an abuse vector and most clouds block outbound 25 anyway.
export const ALLOWED_SMTP_PORTS = [587, 465, 2525]

// Small on purpose: pools are per worker process, so the effective ceiling against a relay's
// per-account connection cap is (processes × maxConnections).
const MAX_POOLED_CONNECTIONS = 2

// Transports are rebuilt after this long so DNS changes and credential rotations are picked up
// without keeping a connection to a stale pinned address forever.
const TRANSPORT_TTL_MS = 5 * 60 * 1000

const CONNECTION_TIMEOUT_MS = 10_000
const GREETING_TIMEOUT_MS = 10_000
const SOCKET_TIMEOUT_MS = 30_000

export type SmtpConnectionConfig = {
    host: string
    port: number
    encryption: 'starttls' | 'ssl' | 'none'
    username?: string
    password?: string
}

export const smtpConfigFromIntegration = (integration: IntegrationType): SmtpConnectionConfig => {
    const { host, port, encryption, username } = integration.config
    const password = integration.sensitive_config?.password

    if (typeof host !== 'string' || !host) {
        throw new Error('The SMTP integration has no host configured')
    }
    if (!ALLOWED_SMTP_PORTS.includes(port)) {
        throw new Error(`The SMTP integration port must be one of ${ALLOWED_SMTP_PORTS.join(', ')}`)
    }
    if (!['starttls', 'ssl', 'none'].includes(encryption)) {
        throw new Error('The SMTP integration has an invalid encryption mode')
    }

    return { host, port, encryption, username: username || undefined, password: password || undefined }
}

// Resolves the SMTP host through the same SSRF-safe lookup the CDP fetch path uses (rejects
// private/link-local/metadata ranges in prod) and returns a single address to pin the
// connection to, closing the DNS-rebinding window between validation and connect.
const resolveSafeSmtpAddress = (host: string): Promise<string> => {
    return new Promise((resolve, reject) => {
        httpStaticLookup(host, { all: true }, (err, addresses) => {
            if (err) {
                return reject(new Error(`Could not resolve SMTP host ${host}: ${err.message}`))
            }
            const first = Array.isArray(addresses) ? addresses[0]?.address : addresses
            if (!first) {
                return reject(new Error(`Could not resolve SMTP host ${host}`))
            }
            resolve(first)
        })
    })
}

type CachedTransport = {
    transport: Transporter
    fingerprint: string
    expiresAt: number
}

/**
 * Pooled nodemailer transports per email integration. The connection is pinned to a
 * pre-validated address while TLS verification (SNI + cert identity) stays on the configured
 * hostname via `servername`. Config changes are picked up by fingerprint comparison on each
 * send — the caller always passes a freshly-loaded integration, so a Django-side update
 * followed by the reload-integrations pubsub takes effect on the next send.
 */
export class SmtpTransportPool {
    private transports = new Map<number, CachedTransport>()

    public async get(integration: IntegrationType): Promise<Transporter> {
        const config = smtpConfigFromIntegration(integration)
        const fingerprint = JSON.stringify([
            config.host,
            config.port,
            config.encryption,
            config.username,
            config.password,
        ])

        const cached = this.transports.get(integration.id)
        if (cached && cached.fingerprint === fingerprint && cached.expiresAt > Date.now()) {
            return cached.transport
        }
        if (cached) {
            cached.transport.close()
            this.transports.delete(integration.id)
        }

        const pinnedAddress = await resolveSafeSmtpAddress(config.host)
        const transport = nodemailer.createTransport({
            pool: true,
            maxConnections: MAX_POOLED_CONNECTIONS,
            host: pinnedAddress,
            port: config.port,
            secure: config.encryption === 'ssl',
            requireTLS: config.encryption === 'starttls',
            ignoreTLS: config.encryption === 'none',
            servername: config.host,
            tls: { servername: config.host },
            auth: config.username ? { user: config.username, pass: config.password } : undefined,
            connectionTimeout: CONNECTION_TIMEOUT_MS,
            greetingTimeout: GREETING_TIMEOUT_MS,
            socketTimeout: SOCKET_TIMEOUT_MS,
        } as SMTPPool.Options)

        this.transports.set(integration.id, { transport, fingerprint, expiresAt: Date.now() + TRANSPORT_TTL_MS })
        return transport
    }

    public closeAll(): void {
        for (const [integrationId, cached] of this.transports) {
            try {
                cached.transport.close()
            } catch (error) {
                logger.warn('[SmtpTransportPool] Failed to close transport', { integrationId, error })
            }
        }
        this.transports.clear()
    }
}

export const smtpTransportPool = new SmtpTransportPool()

registerShutdownHandler(() => {
    smtpTransportPool.closeAll()
    return Promise.resolve()
})
