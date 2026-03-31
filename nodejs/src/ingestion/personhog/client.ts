import { Transport, createClient } from '@connectrpc/connect'
import { createGrpcTransport } from '@connectrpc/connect-node'

import { PersonHogService } from '../../generated/personhog/personhog/service/v1/service_pb'
import { PersonHogGroupOperations } from './groups'

export interface PersonHogClientConfig {
    addr: string
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

    private constructor(transport: Transport) {
        const client = createClient(PersonHogService, transport)
        this.groups = new PersonHogGroupOperations(client)
    }

    static fromTransport(transport: Transport): PersonHogClient {
        return new PersonHogClient(transport)
    }

    static fromConfig(config: PersonHogClientConfig): PersonHogClient {
        const scheme = config.useTls ? 'https' : 'http'
        const transport = createGrpcTransport({
            baseUrl: `${scheme}://${config.addr}`,
            defaultTimeoutMs: config.timeoutMs ?? 5_000,
            readMaxBytes: config.readMaxBytes ?? 128 * 1024 * 1024,
            writeMaxBytes: config.writeMaxBytes ?? 4 * 1024 * 1024,
            pingIntervalMs: config.pingIntervalMs ?? 30_000,
            pingTimeoutMs: config.pingTimeoutMs ?? 5_000,
            pingIdleConnection: config.pingIdleConnection ?? true,
        })
        return new PersonHogClient(transport)
    }
}
