import diagnosticsChannel from 'node:diagnostics_channel'
import type { Socket } from 'node:net'

import { logger } from '~/common/utils/logger'

// Records which APNs connection carried each 403, so a rejection can be tied to the Apple server that sent it.
// fetch does not expose the socket, so this listens on undici's diagnostics channels instead.

const APNS_HOSTNAMES = new Set(['api.push.apple.com', 'api.sandbox.push.apple.com'])
const REJECTED_CONNECTIONS_MAX = 1000

export type ApnsConnection = {
    connectionId: number
    remoteAddress: string | undefined
    remotePort: number | undefined
    localPort: number | undefined
}

type UndiciRequest = { origin?: string | URL }

let subscribed = false
let nextConnectionId = 1
const connectionBySocket = new WeakMap<Socket, ApnsConnection>()
const connectionByRequest = new WeakMap<object, ApnsConnection>()
// Keyed by the apns-id Apple returns. The caller reads it right after the response, so entries stay few.
const rejectedConnectionByApnsId = new Map<string, ApnsConnection>()

// Runs for every request this process sends, so the cheap substring test comes before the URL parse.
function isApnsOrigin(origin: string | URL | undefined): boolean {
    if (origin === undefined) {
        return false
    }
    const value = String(origin)
    return value.includes('push.apple.com') && APNS_HOSTNAMES.has(new URL(value).hostname)
}

function connectionFor(socket: Socket): ApnsConnection {
    let connection = connectionBySocket.get(socket)
    if (!connection) {
        connection = {
            connectionId: nextConnectionId++,
            remoteAddress: socket.remoteAddress,
            remotePort: socket.remotePort,
            localPort: socket.localPort,
        }
        connectionBySocket.set(socket, connection)
    }
    return connection
}

// HTTP/1.1 responses carry a flat [name, value, ...] array. HTTP/2 responses carry Node's lowercase header object.
function headerValue(rawHeaders: unknown, name: string): string | undefined {
    if (Array.isArray(rawHeaders)) {
        for (let i = 0; i + 1 < rawHeaders.length; i += 2) {
            if (String(rawHeaders[i]).toLowerCase() === name) {
                return String(rawHeaders[i + 1])
            }
        }
        return undefined
    }
    if (rawHeaders && typeof rawHeaders === 'object') {
        const value = (rawHeaders as Record<string, unknown>)[name]
        return value === undefined ? undefined : String(value)
    }
    return undefined
}

// Node reports a throwing subscriber as an uncaught exception, which would take the worker down for a log line.
function safely(handler: (message: unknown) => void): (message: unknown) => void {
    return (message) => {
        try {
            handler(message)
        } catch (error) {
            logger.warn('🍎', 'APNs connection diagnostics failed', { error: String(error) })
        }
    }
}

export function subscribeApnsConnectionDiagnostics(): void {
    if (subscribed) {
        return
    }
    subscribed = true

    diagnosticsChannel.subscribe(
        'undici:client:connected',
        safely((message) => {
            const { connectParams, socket } = message as { connectParams?: { hostname?: string }; socket?: Socket }
            if (!socket || !connectParams?.hostname || !APNS_HOSTNAMES.has(connectParams.hostname)) {
                return
            }
            logger.info('🍎', 'APNs connection opened', connectionFor(socket))
        })
    )

    diagnosticsChannel.subscribe(
        'undici:client:sendHeaders',
        safely((message) => {
            // The message also carries the request headers, which include the provider token. Never read or log them.
            const { request, socket } = message as { request?: UndiciRequest; socket?: Socket }
            if (request && socket && isApnsOrigin(request.origin)) {
                connectionByRequest.set(request, connectionFor(socket))
            }
        })
    )

    diagnosticsChannel.subscribe(
        'undici:request:headers',
        safely((message) => {
            const { request, response } = message as {
                request?: UndiciRequest
                response?: { statusCode?: number; headers?: unknown }
            }
            if (!request || response?.statusCode !== 403 || !isApnsOrigin(request.origin)) {
                return
            }
            const connection = connectionByRequest.get(request)
            const apnsId = headerValue(response.headers, 'apns-id')
            if (!connection || !apnsId) {
                return
            }
            if (rejectedConnectionByApnsId.size >= REJECTED_CONNECTIONS_MAX) {
                const oldest = rejectedConnectionByApnsId.keys().next().value
                if (oldest !== undefined) {
                    rejectedConnectionByApnsId.delete(oldest)
                }
            }
            rejectedConnectionByApnsId.set(apnsId, connection)
        })
    )
}

export function takeRejectedApnsConnection(apnsId: string | undefined): ApnsConnection | undefined {
    if (!apnsId) {
        return undefined
    }
    const connection = rejectedConnectionByApnsId.get(apnsId)
    rejectedConnectionByApnsId.delete(apnsId)
    return connection
}
