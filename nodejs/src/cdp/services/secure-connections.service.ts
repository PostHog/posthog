import jwt from 'jsonwebtoken'
import http from 'node:http'
import https from 'node:https'
import net from 'node:net'

import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import {
    FetchOptions,
    FetchResponse,
    SecureRequestError,
    _fetch,
    createTrustedDispatcher,
} from '~/common/utils/request'

const MAGIC_HOST_SUFFIX = '.secure-connections.internal'
const CONNECTION_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const HOSTNAME_PATTERN =
    /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i

type ApprovedConnection = {
    name: string
    selector_kind: string
    selector: string
}

type ApprovalRow = {
    cdp_approved_connections: Record<string, ApprovedConnection>
}

export type SecureConnectionsServiceConfig = {
    workerUrl: string
    workloadSecret: string
}

export function connectionIdFromMagicHostname(hostname: string): string | null {
    const normalized = hostname.toLowerCase()
    if (!normalized.endsWith(MAGIC_HOST_SUFFIX)) {
        return null
    }
    const connectionId = normalized.slice(0, -MAGIC_HOST_SUFFIX.length)
    return CONNECTION_ID_PATTERN.test(connectionId) ? connectionId : null
}

export function magicHostnameForConnection(connectionId: string): string {
    return `${connectionId}.secure-connections.internal`
}

export class SecureConnectionsService {
    constructor(
        private postgres: PostgresRouter,
        private config: SecureConnectionsServiceConfig
    ) {}

    isSecureConnectionUrl(url: string): boolean {
        try {
            return connectionIdFromMagicHostname(new URL(url).hostname) !== null
        } catch {
            return false
        }
    }

    async fetch(teamId: number, url: string, options: FetchOptions): Promise<FetchResponse> {
        const parsedUrl = new URL(url)
        const connectionId = connectionIdFromMagicHostname(parsedUrl.hostname)
        if (!connectionId) {
            throw new SecureRequestError('Invalid Secure connection hostname')
        }
        if (parsedUrl.protocol !== 'http:') {
            throw new SecureRequestError(
                'CDP currently supports HTTP services through Secure connections. HTTPS requires a port-routed connection with explicit TLS server-name metadata.'
            )
        }

        const approval = await this.getApprovedConnection(teamId, connectionId)
        if (!approval) {
            throw new SecureRequestError(
                `Secure connection ${connectionId} is not approved for CDP in this project. Ask a project admin to approve it in Secure connections settings.`
            )
        }
        if (approval.selector_kind !== 'hostname' || !HOSTNAME_PATTERN.test(approval.selector)) {
            throw new SecureRequestError('Secure connection has invalid CDP routing metadata')
        }
        if (!this.config.workerUrl || !this.config.workloadSecret) {
            throw new SecureRequestError('Secure connections are not configured for the CDP worker')
        }

        const grant = this.createWorkloadGrant(teamId, connectionId)
        const dispatcher = this.createDispatcher(connectionId, grant)
        const headers = { ...(options.headers as Record<string, string> | undefined), host: approval.selector }
        try {
            const response = await _fetch(url, { ...options, headers }, dispatcher)
            let closed = false
            const close = async (): Promise<void> => {
                if (!closed) {
                    closed = true
                    await dispatcher.close()
                }
            }
            return {
                ...response,
                json: async () => {
                    try {
                        return await response.json()
                    } finally {
                        await close()
                    }
                },
                text: async () => {
                    try {
                        return await response.text()
                    } finally {
                        await close()
                    }
                },
                dump: async () => {
                    try {
                        await response.dump()
                    } finally {
                        await close()
                    }
                },
            }
        } catch (error) {
            await dispatcher.close()
            throw error
        }
    }

    private async getApprovedConnection(teamId: number, connectionId: string): Promise<ApprovedConnection | null> {
        const result = await this.postgres.query<ApprovalRow>(
            PostgresUse.COMMON_WRITE,
            `SELECT extra_settings -> 'secure_connections' -> 'cdp_approved_connections' AS cdp_approved_connections
             FROM posthog_team
             WHERE id = $1`,
            [teamId],
            'secure-connections-cdp-approval'
        )
        return result.rows[0]?.cdp_approved_connections?.[connectionId] ?? null
    }

    private createWorkloadGrant(teamId: number, connectionId: string): string {
        return jwt.sign(
            {
                iss: 'posthog',
                sub: 'cdp-cyclotron-worker',
                team_id: String(teamId),
                connection_id: connectionId,
                scopes: ['forward'],
            },
            this.config.workloadSecret,
            { algorithm: 'HS256', audience: 'burrow-worker', expiresIn: 120, keyid: 'current' }
        )
    }

    private createDispatcher(connectionId: string, grant: string): ReturnType<typeof createTrustedDispatcher> {
        return createTrustedDispatcher((_options, callback) => {
            this.openTunnel(connectionId, grant)
                .then((socket) => callback(null, socket))
                .catch((error) => callback(error, null))
        })
    }

    private async openTunnel(connectionId: string, grant: string): Promise<net.Socket> {
        const workerUrl = new URL(this.config.workerUrl)
        const requestModule = workerUrl.protocol === 'https:' ? https : http
        return await new Promise((resolve, reject) => {
            const request = requestModule.request({
                protocol: workerUrl.protocol,
                hostname: workerUrl.hostname,
                port: workerUrl.port,
                method: 'CONNECT',
                path: `/v1/connections/${connectionId}`,
                headers: { Authorization: `Bearer ${grant}` },
            })
            request.once('connect', (response, socket, head) => {
                if (response.statusCode !== 200) {
                    socket.destroy()
                    reject(
                        new SecureRequestError(`Secure connection worker rejected the tunnel (${response.statusCode})`)
                    )
                    return
                }
                if (head.length) {
                    socket.unshift(head)
                }
                resolve(socket)
            })
            request.once('response', (response) => {
                reject(new SecureRequestError(`Secure connection worker rejected the tunnel (${response.statusCode})`))
            })
            request.once('error', reject)
            request.end()
        })
    }
}
