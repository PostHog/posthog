import { type Transport, createClient } from '@connectrpc/connect'
import { Http2SessionManager, createGrpcTransport } from '@connectrpc/connect-node'
import * as http2 from 'node:http2'
import * as net from 'node:net'

import { PersonHogService } from '~/common/generated/personhog/personhog/service/v1/service_pb'

import { createPersonhogTransport } from './client'
import { SingleFrameRequestSessionManager } from './single-frame-request-session-manager'

const CLIENT_PREFACE_BYTES = 24
const DATA_FRAME = 0
const END_STREAM = 0x1

type DataFrame = { streamId: number; length: number; endStream: boolean }

/** Forwards a client's bytes to a server and records the DATA frames the client sent. */
function recordClientDataFrames(upstreamPort: number): {
    proxy: net.Server
    frames: DataFrame[]
    sockets: Set<net.Socket>
} {
    const frames: DataFrame[] = []
    const sockets = new Set<net.Socket>()
    const proxy = net.createServer((client) => {
        const upstream = net.connect(upstreamPort, '127.0.0.1')
        sockets.add(client)
        sockets.add(upstream)
        client.pipe(upstream)
        upstream.pipe(client)
        let pending = Buffer.alloc(0)
        let prefaceSkipped = false
        client.on('data', (chunk: Buffer) => {
            pending = Buffer.concat([pending, chunk])
            if (!prefaceSkipped) {
                if (pending.length < CLIENT_PREFACE_BYTES) {
                    return
                }
                pending = pending.subarray(CLIENT_PREFACE_BYTES)
                prefaceSkipped = true
            }
            while (pending.length >= 9) {
                const length = pending.readUIntBE(0, 3)
                if (pending.length < 9 + length) {
                    break
                }
                const streamId = pending.readUInt32BE(5) & 0x7fffffff
                if (pending[3] === DATA_FRAME && streamId > 0) {
                    frames.push({ streamId, length, endStream: (pending[4] & END_STREAM) !== 0 })
                }
                pending = pending.subarray(9 + length)
            }
        })
        client.on('error', () => upstream.destroy())
        upstream.on('error', () => client.destroy())
    })
    return { proxy, frames, sockets }
}

type TransportFactory = (addr: string) => { transport: Transport; close: () => void }

const personhogTransport: TransportFactory = (addr) => {
    const { transport, stateMonitor } = createPersonhogTransport({ addr, timeoutMs: 2_000 })
    return { transport, close: () => stateMonitor.close() }
}

const plainConnectTransport: TransportFactory = (addr) => {
    const sessionManager = new Http2SessionManager(`http://${addr}`)
    const transport = createGrpcTransport({ baseUrl: `http://${addr}`, sessionManager, defaultTimeoutMs: 2_000 })
    return { transport, close: () => sessionManager.abort() }
}

async function sendOneRequest(makeTransport: TransportFactory): Promise<DataFrame[]> {
    const server = http2.createServer()
    const sessions: http2.ServerHttp2Session[] = []
    server.on('session', (session) => sessions.push(session))
    server.on('stream', (stream: http2.ServerHttp2Stream) => {
        stream.resume()
        stream.on('end', () => {
            stream.respond({ ':status': 200, 'content-type': 'application/grpc' }, { waitForTrailers: true })
            stream.on('wantTrailers', () => stream.sendTrailers({ 'grpc-status': '0' }))
            stream.end(Buffer.from([0, 0, 0, 0, 0]))
        })
    })
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const { proxy, frames, sockets } = recordClientDataFrames((server.address() as net.AddressInfo).port)
    await new Promise<void>((resolve) => proxy.listen(0, '127.0.0.1', resolve))
    const { transport, close } = makeTransport(`127.0.0.1:${(proxy.address() as net.AddressInfo).port}`)
    try {
        await createClient(PersonHogService, transport).getPerson({ teamId: 1n, personId: 1n })
        return frames
    } finally {
        close()
        for (const session of sessions) {
            session.destroy()
        }
        for (const socket of sockets) {
            socket.destroy()
        }
        await new Promise<void>((resolve) => proxy.close(() => resolve()))
        await new Promise<void>((resolve) => server.close(() => resolve()))
    }
}

describe('SingleFrameRequestSessionManager', () => {
    it.each([
        ['the personhog transport', 'in the body frame', personhogTransport, [{ endStream: true, carriesBody: true }]],
        [
            'plain connect-node',
            'in a frame of its own',
            plainConnectTransport,
            [
                { endStream: false, carriesBody: true },
                { endStream: true, carriesBody: false },
            ],
        ],
    ])('%s sends a unary request end of stream %s', async (_client, _framing, makeTransport, expected) => {
        const frames = await sendOneRequest(makeTransport)

        expect(frames.map((frame) => ({ endStream: frame.endStream, carriesBody: frame.length > 0 }))).toEqual(expected)
    })

    it('writes the earlier chunks of a multi-chunk body in order and sends the last with end', async () => {
        const writes: unknown[] = []
        const ends: unknown[][] = []
        const stream = {
            write: (data: unknown) => {
                writes.push(data)
                return true
            },
            end: (...args: unknown[]) => {
                ends.push(args)
                return stream
            },
        }
        const inner = {
            authority: 'localhost:1',
            request: jest.fn().mockResolvedValue(stream),
            notifyResponseByteRead: jest.fn(),
        }
        const manager = new SingleFrameRequestSessionManager(inner as any)
        const wrapped = (await manager.request('POST', '/svc/Method', {}, {})) as any

        const acknowledged: string[] = []
        wrapped.write('first', 'binary', () => acknowledged.push('first'))
        wrapped.write('second', 'binary', () => acknowledged.push('second'))
        const finished = jest.fn()
        wrapped.end(finished)
        await new Promise((resolve) => process.nextTick(resolve))

        expect(writes).toEqual(['first'])
        expect(ends).toEqual([['second', 'binary', finished]])
        expect(acknowledged).toEqual(['first', 'second'])
    })
})
