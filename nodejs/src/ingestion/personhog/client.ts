import { create } from '@bufbuild/protobuf'
import { Interceptor, Transport, createClient } from '@connectrpc/connect'
import { Http2SessionManager, createGrpcTransport } from '@connectrpc/connect-node'
import { DateTime } from 'luxon'

import { PersonHogService } from '../../generated/personhog/personhog/service/v1/service_pb'
import { ConsistencyLevel, ReadOptionsSchema } from '../../generated/personhog/personhog/types/v1/common_pb'
import { parseJSON } from '../../utils/json-parse'
import { PersonHogGroupOperations } from './groups'
import { PersonHogPersonOperations } from './persons'
import { SessionStateMonitor } from './session-state-monitor'

const textDecoder = new TextDecoder()

export function parseJsonBytes(bytes: Uint8Array): any {
    if (bytes.length === 0) {
        return null
    }
    return parseJSON(textDecoder.decode(bytes))
}

export function epochMsToDateTime(epochMs: bigint): DateTime {
    return DateTime.fromMillis(Number(epochMs), { zone: 'utc' })
}

export function shouldUseGrpc(percentage: number): boolean {
    return Math.random() * 100 < percentage
}

export function eventualReadOptions() {
    return create(ReadOptionsSchema, { consistency: ConsistencyLevel.EVENTUAL })
}

export interface PersonHogClientConfig {
    /** Host and port of the personhog gRPC server, e.g. "localhost:50051". */
    addr: string
    /** Identifier sent in the x-client-name header so the server can distinguish callers. */
    clientName?: string
    /** Use TLS (https) for the HTTP/2 connection. Default: false. */
    useTls?: boolean

    // -- Request limits --

    /** Per-request timeout in milliseconds. Default: 5 000. */
    timeoutMs?: number
    /** Maximum inbound message size in bytes. Default: 128 MiB. */
    readMaxBytes?: number
    /** Maximum outbound message size in bytes. Default: 4 MiB. */
    writeMaxBytes?: number

    // -- HTTP/2 keepalive (maps to gRPC keepalive concepts) --

    /**
     * Interval between HTTP/2 PING frames to keep the connection alive.
     * The interval resets whenever a stream receives data. If a PING is not
     * answered within pingTimeoutMs the connection is closed.
     * Equivalent to GRPC_ARG_KEEPALIVE_TIME_MS. Default: 30 000.
     */
    pingIntervalMs?: number
    /**
     * How long to wait for a PING response before treating the connection as
     * dead. Equivalent to GRPC_ARG_KEEPALIVE_TIMEOUT_MS. Default: 5 000.
     */
    pingTimeoutMs?: number
    /**
     * Send PING frames even when no streams are open. Keeps idle connections
     * alive so they don't get silently dropped by load balancers or proxies.
     * Equivalent to GRPC_ARG_KEEPALIVE_PERMIT_WITHOUT_CALLS. Default: true.
     */
    pingIdleConnection?: boolean
    /**
     * Close the HTTP/2 connection after this many milliseconds of no open
     * streams. A new connection is created transparently on the next request.
     * Equivalent to GRPC_ARG_CLIENT_IDLE_TIMEOUT_MS. Default: 15 minutes.
     */
    idleConnectionTimeoutMs?: number

    // -- Observability --

    /**
     * How often (ms) to poll the Http2SessionManager state for connection
     * state transition metrics. Lower values detect async transitions (idle
     * timeouts, ping failures) faster but add minor CPU overhead.
     * Default: 5 000.
     */
    stateMonitorPollIntervalMs?: number
}

export class PersonHogClient {
    readonly groups: PersonHogGroupOperations
    readonly persons: PersonHogPersonOperations

    private stateMonitor: SessionStateMonitor | undefined

    private constructor(transport: Transport, stateMonitor?: SessionStateMonitor) {
        const client = createClient(PersonHogService, transport)
        this.groups = new PersonHogGroupOperations(client)
        this.persons = new PersonHogPersonOperations(client)
        this.stateMonitor = stateMonitor
    }

    static fromTransport(transport: Transport): PersonHogClient {
        return new PersonHogClient(transport)
    }

    static fromConfig(config: PersonHogClientConfig): PersonHogClient {
        const scheme = config.useTls ? 'https' : 'http'
        const interceptors: Interceptor[] = []
        if (config.clientName) {
            const clientName = config.clientName
            interceptors.push((next) => async (req) => {
                req.header.set('x-client-name', clientName)
                return await next(req)
            })
        }

        const sessionManager = new Http2SessionManager(`${scheme}://${config.addr}`, {
            pingIntervalMs: config.pingIntervalMs ?? 30_000,
            pingTimeoutMs: config.pingTimeoutMs ?? 5_000,
            pingIdleConnection: config.pingIdleConnection ?? true,
            idleConnectionTimeoutMs: config.idleConnectionTimeoutMs,
        })

        const stateMonitor = new SessionStateMonitor(
            sessionManager,
            config.clientName ?? 'unknown',
            config.stateMonitorPollIntervalMs ?? 5_000
        )

        const transport = createGrpcTransport({
            baseUrl: `${scheme}://${config.addr}`,
            defaultTimeoutMs: config.timeoutMs ?? 5_000,
            readMaxBytes: config.readMaxBytes ?? 128 * 1024 * 1024,
            writeMaxBytes: config.writeMaxBytes ?? 4 * 1024 * 1024,
            sessionManager: stateMonitor,
            interceptors,
        })
        return new PersonHogClient(transport, stateMonitor)
    }

    close(): void {
        this.stateMonitor?.close()
    }
}
