import { Server, createServer } from 'http'
import { AddressInfo, Socket, connect } from 'net'

import { capIdleConnections } from './idle-connections'

describe('capIdleConnections', () => {
    let server: Server
    let port: number
    const sockets: Socket[] = []

    beforeEach(async () => {
        server = createServer((req, res) => {
            if (req.url === '/slow') {
                setTimeout(() => res.end('ok'), 200)
                return
            }
            res.end('ok')
        })
        server.keepAliveTimeout = 60_000
        capIdleConnections(server, 2)
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        port = (server.address() as AddressInfo).port
    })

    afterEach(async () => {
        sockets.splice(0).forEach((socket) => socket.destroy())
        await new Promise((resolve) => server.close(resolve))
    })

    const open = async (): Promise<Socket> => {
        const socket = connect(port, '127.0.0.1')
        sockets.push(socket)
        await new Promise((resolve) => socket.once('connect', resolve))
        return socket
    }

    const request = (socket: Socket, path = '/'): Promise<void> =>
        new Promise((resolve) => {
            socket.once('data', () => resolve())
            socket.write(`GET ${path} HTTP/1.1\r\nHost: localhost\r\nConnection: keep-alive\r\n\r\n`)
        })

    const isOpen = async (socket: Socket): Promise<boolean> => {
        await new Promise((resolve) => setTimeout(resolve, 50))
        return !socket.destroyed && !socket.readableEnded
    }

    it('closes the longest-idle connections beyond the limit and keeps the rest', async () => {
        const [first, second, third] = [await open(), await open(), await open()]
        for (const socket of [first, second, third]) {
            await request(socket)
        }

        expect(await isOpen(first)).toBe(false)
        expect(await isOpen(second)).toBe(true)
        expect(await isOpen(third)).toBe(true)
        await request(second)
    })

    it('never closes a connection that is serving a request', async () => {
        const busy = await open()
        const finished = request(busy, '/slow')
        for (let i = 0; i < 3; i++) {
            await request(await open())
        }

        await finished
        expect(await isOpen(busy)).toBe(true)
    })
})
