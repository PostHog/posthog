import net, { AddressInfo } from 'net'

// The edge answers an encryption request "no", so the client speaks the plain wire protocol it can read.
const SSL_REQUEST = 80877103
const GSSENC_REQUEST = 80877104
const DECLINED = Buffer.from('N')
const PARSE = 'P'.charCodeAt(0)
const QUERY = 'Q'.charCodeAt(0)
const REFUSED_TABLE = 'cyclotron_jobs_refused_by_the_scenario_edge'
const DEFAULT_PORT = 5432

export type PgProxy = { url: string; close(): Promise<void> }

// A refused statement names a table that does not exist, so Postgres answers it with its own error and handles the
// transaction it fails and the rest of the client's pipeline as it would for any failed statement.
function refused(message: Buffer, refuses: (statement: string) => boolean): Buffer {
    const type = message[0]
    if (type !== PARSE && type !== QUERY) {
        return message
    }
    const start = type === PARSE ? message.indexOf(0, 5) + 1 : 5
    const end = message.indexOf(0, start)
    const statement = message.toString('utf8', start, end)
    if (!refuses(statement)) {
        return message
    }
    const body = Buffer.concat([
        message.subarray(5, start),
        Buffer.from(statement.replace(/cyclotron_jobs\b/i, REFUSED_TABLE)),
        message.subarray(end),
    ])
    const header = Buffer.alloc(5)
    header[0] = type
    header.writeInt32BE(body.length + 4, 1)
    return Buffer.concat([header, body])
}

function clientMessages(
    forward: (message: Buffer) => void,
    decline: () => void,
    refuses: (statement: string) => boolean
): (chunk: Buffer) => void {
    let pending = Buffer.alloc(0)
    let started = false
    return (chunk) => {
        pending = Buffer.concat([pending, chunk])
        for (;;) {
            const headerBytes = started ? 5 : 8
            if (pending.length < headerBytes) {
                return
            }
            const length = started ? pending.readInt32BE(1) + 1 : pending.readInt32BE(0)
            if (pending.length < length) {
                return
            }
            const message = pending.subarray(0, length)
            pending = pending.subarray(length)
            if (started) {
                forward(refused(message, refuses))
                continue
            }
            const code = message.readInt32BE(4)
            if (code === SSL_REQUEST || code === GSSENC_REQUEST) {
                decline()
                continue
            }
            started = true
            forward(message)
        }
    }
}

export async function startPgProxy(upstream: string, refuses: (statement: string) => boolean): Promise<PgProxy> {
    const target = new URL(upstream)
    const sockets = new Set<net.Socket>()
    const track = (socket: net.Socket): net.Socket => {
        sockets.add(socket)
        socket.once('close', () => sockets.delete(socket))
        return socket
    }
    const proxy = net.createServer((client) => {
        const server = track(net.connect({ host: target.hostname, port: Number(target.port || DEFAULT_PORT) }))
        track(client)
        const read = clientMessages(
            (message) => server.write(message),
            () => client.write(DECLINED),
            refuses
        )
        client.on('data', read)
        server.on('data', (chunk) => client.write(chunk))
        for (const [socket, other] of [
            [client, server],
            [server, client],
        ]) {
            socket.on('error', () => other.destroy())
            socket.on('close', () => other.destroy())
        }
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
