import net, { AddressInfo } from 'net'

// The edge answers an encryption request "no", so the client speaks the plain wire protocol it can read.
const SSL_REQUEST = 80877103
const GSSENC_REQUEST = 80877104
const DECLINED = Buffer.from('N')
const PARSE = 'P'.charCodeAt(0)
const QUERY = 'Q'.charCodeAt(0)
const ERROR_RESPONSE = 'E'.charCodeAt(0)
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

export type PgRefusals = { refusePg(): string | undefined; pgRefusalAnswered(token: string): void }

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

// A refused enqueue names a table that does not exist, so Postgres answers it with its own error and handles the
// transaction it fails and the rest of the client's pipeline as it would for any failed statement.
function refusedMessage(message: Buffer, refusals: PgRefusals): Buffer | undefined {
    const type = message[0]
    if (type !== PARSE && type !== QUERY) {
        return undefined
    }
    const start = type === PARSE ? message.indexOf(0, TYPED_HEADER_BYTES) + 1 : TYPED_HEADER_BYTES
    const end = message.indexOf(0, start)
    const statement = message.toString('utf8', start, end)
    if (!ENQUEUE.test(statement)) {
        return undefined
    }
    const token = refusals.refusePg()
    if (token === undefined) {
        return undefined
    }
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

function connect(client: net.Socket, server: net.Socket, refusals: PgRefusals): void {
    let started = false
    const fromClient = framesOf(
        () => (started ? TYPED_HEADER_BYTES : STARTUP_MIN_BYTES),
        (header) => (started ? typedLength(header) : startupLength(header)),
        (message) => {
            if (started) {
                server.write(refusedMessage(message, refusals) ?? message)
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
    const fromServer = framesOf(
        () => TYPED_HEADER_BYTES,
        typedLength,
        (message) => {
            const token = refusalTokenOf(message)
            client.write(message, (error) => {
                if (token !== undefined && !error) {
                    refusals.pgRefusalAnswered(token)
                }
            })
        }
    )
    relay(client, server, fromClient)
    relay(server, client, fromServer)
}

export async function startPgProxy(upstream: string, refusals: PgRefusals): Promise<PgProxy> {
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
    const proxy = net.createServer({ allowHalfOpen: true }, (client) => {
        const server = net.connect({
            host: target.hostname,
            port: Number(target.port || DEFAULT_PORT),
            allowHalfOpen: true,
        })
        connect(track(client), track(server), refusals)
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
