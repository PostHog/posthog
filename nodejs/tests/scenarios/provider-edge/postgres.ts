import net, { AddressInfo } from 'net'

// The edge answers an encryption request "no", so the client speaks the plain wire protocol it can read.
const SSL_REQUEST = 80877103
const GSSENC_REQUEST = 80877104
const DECLINED = Buffer.from('N')
const PARSE = 'P'.charCodeAt(0)
const QUERY = 'Q'.charCodeAt(0)
const SYNC = 'S'.charCodeAt(0)
const FUNCTION_CALL = 'F'.charCodeAt(0)
const ERROR_RESPONSE = 'E'.charCodeAt(0)
const COMMAND_COMPLETE = 'C'.charCodeAt(0)
const READY_FOR_QUERY = 'Z'.charCodeAt(0)
const IDLE = 'I'.charCodeAt(0)
const IN_TRANSACTION = 'T'.charCodeAt(0)
const ROLLED_BACK = Buffer.from('ROLLBACK\0')
const ROWS_INSERTED = /^INSERT \d+ [1-9]\d*\0$/
const MESSAGE_FIELD = 'M'.charCodeAt(0)
const DEFAULT_PORT = 5432
const STARTUP_MIN_BYTES = 8
// Postgres itself refuses a startup packet above 10000 bytes.
const STARTUP_MAX_BYTES = 10000
const TYPED_HEADER_BYTES = 5
const TYPED_MIN_LENGTH = 4
// pg connects to these query parameters over the URL's host and port, so a URL that names one would bypass the proxy.
const ENDPOINT_PARAMETERS = ['host', 'hostaddr', 'port']

const ENQUEUE = /^(\s*INSERT\s+INTO\s+)cyclotron_jobs(?![\w$.])/i
const REFUSED = /cyclotron_jobs_refused_([0-9a-f]{32})/

export type PgFaults = {
    refusePg(): string | undefined
    pgRefusalAnswered(token: string): void
    losePgCommitReply(): boolean
}

export type PgProxy = { url: string; close(): Promise<void> }

class FrameError extends Error {}

// Reads length-prefixed frames out of a stream, copying each frame's bytes once.
function framesOf(
    headerBytes: () => number,
    lengthOf: (header: Buffer) => number,
    onFrame: (frame: Buffer) => void
): (chunk: Buffer) => void {
    let chunks: Buffer[] = []
    let buffered = 0
    let needed: number | undefined
    const flatten = (): Buffer => {
        if (chunks.length > 1) {
            chunks = [Buffer.concat(chunks, buffered)]
        }
        return chunks[0]
    }
    return (chunk) => {
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

function typedLength(header: Buffer): number {
    const length = header.readInt32BE(1)
    if (length < TYPED_MIN_LENGTH) {
        throw new FrameError(`a message declares ${length} bytes`)
    }
    return length + 1
}

function startupLength(header: Buffer): number {
    const length = header.readInt32BE(0)
    if (length < STARTUP_MIN_BYTES || length > STARTUP_MAX_BYTES) {
        throw new FrameError(`a startup packet declares ${length} bytes`)
    }
    return length
}

type Enqueue = { start: number; end: number; statement: string }

function enqueueOf(message: Buffer): Enqueue | undefined {
    const type = message[0]
    if (type !== PARSE && type !== QUERY) {
        return undefined
    }
    const start = type === PARSE ? message.indexOf(0, TYPED_HEADER_BYTES) + 1 : TYPED_HEADER_BYTES
    const end = message.indexOf(0, start)
    const statement = message.toString('utf8', start, end)
    return ENQUEUE.test(statement) ? { start, end, statement } : undefined
}

// A refused enqueue names a table that does not exist, so Postgres answers it with its own error and handles the
// transaction it fails and the rest of the client's pipeline as it would for any failed statement.
function refusedMessage(message: Buffer, { start, end, statement }: Enqueue, token: string): Buffer {
    const type = message[0]
    const body = Buffer.concat([
        message.subarray(TYPED_HEADER_BYTES, start),
        Buffer.from(statement.replace(ENQUEUE, `$1cyclotron_jobs_refused_${token}`)),
        message.subarray(end),
    ])
    const header = Buffer.alloc(TYPED_HEADER_BYTES)
    header[0] = type
    header.writeInt32BE(body.length + 4, 1)
    return Buffer.concat([header, body])
}

export function refusalTokenOf(message: Buffer): string | undefined {
    if (message[0] !== ERROR_RESPONSE) {
        return undefined
    }
    for (let at = TYPED_HEADER_BYTES; at < message.length && message[at] !== 0; ) {
        const end = message.indexOf(0, at + 1)
        if (end === -1) {
            return undefined
        }
        if (message[at] === MESSAGE_FIELD) {
            return REFUSED.exec(message.toString('utf8', at + 1, end))?.[1]
        }
        at = end + 1
    }
    return undefined
}

// Postgres has committed a transaction once it reports the connection idle again, unless a statement since the last
// report failed or ended the transaction with a rollback.
function committed(replies: Buffer[]): boolean {
    return replies.every(
        (reply) =>
            reply[0] !== ERROR_RESPONSE &&
            !(reply[0] === COMMAND_COMPLETE && reply.subarray(TYPED_HEADER_BYTES).equals(ROLLED_BACK))
    )
}

const insertedRows = (reply: Buffer): boolean =>
    reply[0] === COMMAND_COMPLETE && ROWS_INSERTED.test(reply.toString('latin1', TYPED_HEADER_BYTES))

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
    // Both sockets stay half open, so a side that finished writing still receives what the other sends it.
    from.on('end', () => to.end())
    from.on('error', () => to.destroy())
    from.on('close', (hadError) => (hadError ? to.destroy() : to.end()))
}

function connect(client: net.Socket, server: net.Socket, faults: PgFaults): void {
    let started = false
    // Postgres answers each simple query and each sync with one ReadyForQuery, in the order the client sent them, so
    // the edge pairs every answer with the cycle it closes and holds only the answers of a cycle that may commit an
    // enqueue. Answers a client reads before its sync pass at once.
    let enqueueInCycle = false
    const cycles: boolean[] = []
    let ready = false
    let insertedInTransaction = false
    let insertedInCycle = false
    let held: Buffer[] = []
    const fromClient = framesOf(
        () => (started ? TYPED_HEADER_BYTES : STARTUP_MIN_BYTES),
        (header) => (started ? typedLength(header) : startupLength(header)),
        (message) => {
            if (started) {
                const enqueue = enqueueOf(message)
                const token = enqueue && faults.refusePg()
                enqueueInCycle ||= enqueue !== undefined
                if (message[0] === QUERY || message[0] === SYNC || message[0] === FUNCTION_CALL) {
                    cycles.push(enqueueInCycle)
                    enqueueInCycle = false
                }
                server.write(enqueue && token ? refusedMessage(message, enqueue, token) : message)
                return
            }
            const code = message.readInt32BE(4)
            if (code === SSL_REQUEST || code === GSSENC_REQUEST) {
                client.write(DECLINED)
                return
            }
            started = true
            server.write(message)
        }
    )
    const answer = (message: Buffer): void => {
        const token = refusalTokenOf(message)
        client.write(message, (error) => {
            if (token !== undefined && !error) {
                faults.pgRefusalAnswered(token)
            }
        })
    }
    const fromServer = framesOf(
        () => TYPED_HEADER_BYTES,
        typedLength,
        (message) => {
            const closesCycle = message[0] === READY_FOR_QUERY
            if (!ready) {
                ready = closesCycle
                answer(message)
                return
            }
            const enqueueCycle = cycles[0] === true
            if (held.length === 0 && !enqueueCycle && !insertedInTransaction) {
                if (closesCycle) {
                    cycles.shift()
                }
                answer(message)
                return
            }
            held.push(message)
            insertedInCycle ||= enqueueCycle && insertedRows(message)
            if (!closesCycle) {
                return
            }
            cycles.shift()
            const replies = held
            const inserted = insertedInTransaction || insertedInCycle
            held = []
            insertedInCycle = false
            const status = message[TYPED_HEADER_BYTES]
            insertedInTransaction = status === IN_TRANSACTION && inserted
            if (status === IDLE && inserted && committed(replies) && faults.losePgCommitReply()) {
                client.destroy()
                server.destroy()
                return
            }
            replies.forEach(answer)
        }
    )
    relay(client, server, fromClient)
    relay(server, client, fromServer)
}

export async function startPgProxy(upstream: string, faults: PgFaults): Promise<PgProxy> {
    const target = new URL(upstream)
    const overrides = ENDPOINT_PARAMETERS.filter((name) => target.searchParams.has(name))
    if (overrides.length > 0) {
        throw new Error(
            `The edge proxies the host and port of a Cyclotron database URL, and this one names ${overrides.join(', ')} in its query: put the endpoint in the URL's host and port.`
        )
    }
    const sockets = new Set<net.Socket>()
    const track = (socket: net.Socket): net.Socket => {
        sockets.add(socket)
        socket.once('close', () => sockets.delete(socket))
        return socket
    }
    // A URL keeps an IPv6 address in brackets, which net would resolve as a hostname.
    const host = target.hostname.replace(/^\[(.*)\]$/, '$1')
    // A query arrives as several frames, each written on its own, and Nagle would hold each one until the peer acknowledged the last.
    const proxy = net.createServer({ allowHalfOpen: true, noDelay: true }, (client) => {
        const server = net.connect({
            host,
            port: Number(target.port || DEFAULT_PORT),
            allowHalfOpen: true,
            noDelay: true,
        })
        connect(track(client), track(server), faults)
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
