import { create } from '@bufbuild/protobuf'
import { Interceptor, Transport, createClient } from '@connectrpc/connect'
import { createGrpcTransport } from '@connectrpc/connect-node'
import { DateTime } from 'luxon'

import { PersonHogService } from '../../generated/personhog/personhog/service/v1/service_pb'
import { ConsistencyLevel, ReadOptionsSchema } from '../../generated/personhog/personhog/types/v1/common_pb'
import { parseJSON } from '../../utils/json-parse'
import { PersonHogGroupOperations } from './groups'
import { PersonHogPersonOperations } from './persons'

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
    addr: string
    clientName?: string
    useTls?: boolean
    timeoutMs?: number
    readMaxBytes?: number
    writeMaxBytes?: number
    pingIntervalMs?: number
    pingTimeoutMs?: number
    pingIdleConnection?: boolean
}

export class PersonHogClient {
    readonly groups: PersonHogGroupOperations
    readonly persons: PersonHogPersonOperations

    private constructor(transport: Transport) {
        const client = createClient(PersonHogService, transport)
        this.groups = new PersonHogGroupOperations(client)
        this.persons = new PersonHogPersonOperations(client)
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
        const transport = createGrpcTransport({
            baseUrl: `${scheme}://${config.addr}`,
            defaultTimeoutMs: config.timeoutMs ?? 5_000,
            readMaxBytes: config.readMaxBytes ?? 128 * 1024 * 1024,
            writeMaxBytes: config.writeMaxBytes ?? 4 * 1024 * 1024,
            pingIntervalMs: config.pingIntervalMs ?? 30_000,
            pingTimeoutMs: config.pingTimeoutMs ?? 5_000,
            pingIdleConnection: config.pingIdleConnection ?? true,
            interceptors,
        })
        return new PersonHogClient(transport)
    }
}
