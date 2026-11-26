import net, { AddressInfo } from 'net'

import { Refusal } from './faults'

// The edge answers an encryption request "no", so the client speaks the plain wire protocol it can read.
const SSL_REQUEST = 80877103
const GSSENC_REQUEST = 80877104
const DECLINED = Buffer.from('N')
const PARSE = 'P'.charCodeAt(0)
const QUERY = 'Q'.charCodeAt(0)
const ERROR_RESPONSE = 'E'.charCodeAt(0)
const MESSAGE_FIELD = 'M'.charCodeAt(0)
const REFUSED_TABLE = 'cyclotron_jobs_refused_by_the_scenario_edge'
const DEFAULT_PORT = 5432
const STARTUP_MIN_BYTES = 8
// Postgres itself refuses a startup packet above 10000 bytes.
const STARTUP_MAX_BYTES = 10000
const TYPED_MIN_LENGTH = 4

export type PgProxy = { url: string; close(): Promise<void> }

class FrameError extends Error {}

// Reads length-prefixed frames out of a stream, copying each frame's bytes once.
function framesOf(headerBytes: () => number, lengthOf: (header: Buffer) => number, onFrame: (frame: Buffer) => void) {
    let chunks: Buffer[] = []
    let buffered = 0
    let needed: number | undefined
    const flatten = (): Buffer => {
        if (chunks.length > 1) {
            chunks = [Buffer.concat(chunks, buffered)]
        }
        return chunks[0]
    }
    return (chunk: Buffer): void => {
        chunks.push(chunk)
        buffered += chunk.length
        for (;;) {
            if (needed === undefined) {
                if (buffered < headerBytes()) {
                    return
                }
                needed = lengthOf(flatten())
            }
            if (buffered < needed) {
                return
            }
            const pending = flatten()
            const frame = pending.subarray(0, needed)
            chunks = needed < pending.length ? [pending.subarray(needed)] : []
            buffered -= needed
            needed = undefined
            onFrame(frame)
        }
    }
}

const typedLength = (header: Buffer): number => {
    const length = header.readInt32BE(1)
    if (length < TYPED_MIN_LENGTH) {
        throw new FrameError(`a message declares ${length} bytes`)
    }
    return length + 1
}

// A refused statement names a table that does not exist, so Postgres answers it with its own error and handles the
// transaction it fails and the rest of the client's pipeline as it would for any failed statement.
function rewritten(message: Buffer, rewrite: (statement: string) => string | undefined): Buffer | undefined {
    const type = message[0]
    if (type !== PARSE && type !== QUERY) {
        return undefined
    }
    const start = type === PARSE ? message.indexOf(0, 5) + 1 : 5
    const end = message.indexOf(0, start)
    const statement = rewrite(message.toString('utf8', start, end))
    if (statement === undefined) {
        return undefined
    }
    const body = Buffer.concat([message.subarray(5, start), Buffer.from(statement), message.subarray(end)])
    const header = Buffer.alloc(5)
    header[0] = type
    header.writeInt32BE(body.length + 4, 1)
    return Buffer.concat([header, body])
}

const ENQUEUE = /(^|;)(\s*INSERT\s+INTO\s+)cyclotron_jobs(?![\w$])/i

export const isEnqueue = (statement: string): boolean => ENQUEUE.test(statement)

const refusedStatementOf = (statement: string): string =>
    statement.replace(ENQUEUE, (_, before: string, insert: string) => `${before}${insert}${REFUSED_TABLE}`)

function answersRefusal(message: Buffer): boolean {
    if (message[0] !== ERROR_RESPONSE) {
        return false
    }
    for (let at = 5; at < message.length && message[at] !== 0; ) {
        const end = message.indexOf(0, at + 1)
        if (message[at] === MESSAGE_FIELD && message.toString('utf8', at + 1, end).includes(REFUSED_TABLE)) {
            return true
        }
        at = end + 1
    }
    return false
}

function relay(from: net.Socket, to: net.Socket, frames: (chunk: Buffer) => void): void {
    from.on('data', (chunk: Buffer) => {
        try {
            frames(chunk)
        } catch (error) {
            from.destroy(error as Error)
            return
        }
        if (to.writableNeedDrain) {
            from.pause()
            to.once('drain', () => from.resume())
        }
    })
    // A clean close half-closes the peer, so it still receives what is queued for it.
    from.on('close', (hadError) => (hadError ? to.destroy() : to.end()))
    from.on('error', () => to.destroy())
}

function connectionOf(client: net.Socket, server: net.Socket, refuse: () => Refusal | undefined): void {
    const pending: Refusal[] = []
    let started = false
    const fromClient = framesOf(
        () => (started ? 5 : STARTUP_MIN_BYTES),
        (header) => {
            if (started) {
                return typedLength(header)
            }
            const length = header.readInt32BE(0)
            if (length < STARTUP_MIN_BYTES || length > STARTUP_MAX_BYTES) {
                throw new FrameError(`a startup packet declares ${length} bytes`)
            }
            return length
        },
        (message) => {
            if (!started) {
                const code = message.readInt32BE(4)
                if (code === SSL_REQUEST || code === GSSENC_REQUEST) {
                    client.write(DECLINED)
                    return
                }
                started = true
                server.write(message)
                return
            }
            const refused = rewritten(message, (statement) => {
                if (!isEnqueue(statement)) {
                    return undefined
                }
                const refusal = refuse()
                if (refusal === undefined) {
                    return undefined
                }
                pending.push(refusal)
                return refusedStatementOf(statement)
            })
            server.write(refused ?? message)
        }
    )
    const fromServer = framesOf(
        () => 5,
        typedLength,
        (message) => {
            const refusal = answersRefusal(message) ? pending.shift() : undefined
            client.write(message, refusal && ((error) => (error ? refusal.lost() : refusal.answered())))
        }
    )
    relay(client, server, fromClient)
    relay(server, client, fromServer)
    for (const socket of [client, server]) {
        socket.once('close', () => {
            for (const refusal of pending.splice(0)) {
                refusal.lost()
            }
        })
    }
}

export async function startPgProxy(upstream: string, refuse: () => Refusal | undefined): Promise<PgProxy> {
    const target = new URL(upstream)
    const sockets = new Set<net.Socket>()
    const track = (socket: net.Socket): net.Socket => {
        sockets.add(socket)
        socket.once('close', () => sockets.delete(socket))
        return socket
    }
    const proxy = net.createServer((client) => {
        const server = track(net.connect({ host: target.hostname, port: Number(target.port || DEFAULT_PORT) }))
        connectionOf(track(client), server, refuse)
    })
    await new Promise<void>((resolve, reject) => {
        proxy.once('error', reject)
        proxy.listen(0, '127.0.0.1', () => {
            proxy.off('error', reject)
            resolve()
        })
    })
    const url = new URL(upstream)
    url.hostname = '127.0.0.1'
    url.port = String((proxy.address() as AddressInfo).port)
    return {
        url: url.toString(),
        close: async () => {
            for (const socket of sockets) {
                socket.destroy()
            }
            await new Promise<void>((resolve) => proxy.close(() => resolve()))
        },
    }
}
