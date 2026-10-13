import { Http2SessionManager } from '@connectrpc/connect-node'
import http2 from 'http2'
import { AddressInfo } from 'net'

// usage-ingestion ends every connection with GOAWAY once it reaches max_connection_age. The
// usage client is idle between flushes, so connect-node destroys the session with a deferred
// error. A flush that arrives before the socket has closed removes the error listeners, and
// without patches/@connectrpc__connect-node@*.patch the error crashes the process
// (https://github.com/connectrpc/connect-es/issues/1768).
describe('Http2SessionManager GOAWAY on an idle connection', () => {
    let server: http2.Http2Server
    const serverSessions: http2.ServerHttp2Session[] = []

    beforeAll(async () => {
        server = http2.createServer()
        server.on('session', (session) => serverSessions.push(session))
        server.on('stream', (stream) => stream.respond({ ':status': 200 }))
        await new Promise<void>((resolve) => server.listen(0, resolve))
    })

    afterAll(async () => {
        serverSessions.forEach((session) => session.destroy())
        await new Promise<void>((resolve) => server.close(() => resolve()))
    })

    it('does not raise the deferred connection error when a request follows the GOAWAY', async () => {
        const { port } = server.address() as AddressInfo
        const manager = new Http2SessionManager(`http://127.0.0.1:${port}`)
        const closeStream = (stream: http2.ClientHttp2Stream): Promise<void> =>
            new Promise((resolve) => {
                stream.once('close', () => resolve())
                stream.close(http2.constants.NGHTTP2_NO_ERROR)
            })
        try {
            const firstRequest = await manager.request('POST', '/', {}, {})
            const conn = (manager as unknown as { s: { conn: http2.ClientHttp2Session } }).s.conn
            await closeStream(firstRequest)
            expect(manager.state()).toBe('idle')

            // Node emits the deferred error right after this socket closes. Jest reports it as an
            // unhandled error when the patch is missing, so the test only has to outlive it.
            const socket = conn.socket
            const socketClosed = new Promise<void>((resolve) => socket.prependOnceListener('close', () => resolve()))

            serverSessions[0].goaway(http2.constants.NGHTTP2_NO_ERROR)
            await new Promise<void>((resolve) => conn.once('goaway', () => resolve()))
            expect(conn.destroyed).toBe(true)

            const secondRequest = await manager.request('POST', '/', {}, {})
            await socketClosed
            await new Promise<void>((resolve) => setImmediate(resolve))
            expect(manager.state()).toBe('open')
            const response = await new Promise<http2.IncomingHttpHeaders>((resolve) =>
                secondRequest.once('response', resolve)
            )
            expect(response[':status']).toBe(200)
            await closeStream(secondRequest)
        } finally {
            manager.abort()
        }
    })
})
