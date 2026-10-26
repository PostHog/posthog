import { Server } from 'http'
import { Socket } from 'net'
import { Counter } from 'prom-client'

const evictedIdleConnections = new Counter({
    name: 'push_api_idle_connections_evicted_total',
    help: 'Idle keep-alive connections closed because the server held more than its idle limit.',
})

/** Closes the longest-idle keep-alive connections once more than `maxIdle` sit idle, so a long
 * keep-alive timeout cannot be used to pile up open sockets. A connection serving a request is never
 * closed here. */
export function capIdleConnections(server: Server, maxIdle: number): void {
    // A Set iterates in insertion order, so the first entry is the connection idle the longest.
    const idle = new Set<Socket>()

    server.on('connection', (socket: Socket) => {
        socket.once('close', () => idle.delete(socket))
    })
    server.on('request', (req, res) => {
        const socket = req.socket
        idle.delete(socket)
        res.once('finish', () => {
            if (socket.destroyed) {
                return
            }
            idle.add(socket)
            for (const oldest of idle) {
                if (idle.size <= maxIdle) {
                    break
                }
                idle.delete(oldest)
                oldest.destroy()
                evictedIdleConnections.inc()
            }
        })
    })
}
