import http from 'http'
import net from 'net'
import { Duplex } from 'stream'
import tls from 'tls'

import { Leaf } from './certificates'

const ESTABLISHED = 'HTTP/1.1 200 Connection Established\r\n\r\n'

export type Proxy = { close(): void }

function targetOf(authority: string | undefined): { host: string; port: number } | undefined {
    const url = URL.parse(`tcp://${authority ?? ''}`)
    const port = Number(url?.port)
    return url && url.hostname && Number.isInteger(port) && port > 0
        ? { host: url.hostname.replace(/^\[(.*)\]$/, '$1'), port }
        : undefined
}

export function serveConnect(server: http.Server, leaves: Map<string, Leaf>, terminated: http.Server): Proxy {
    const open = new Set<Duplex>()
    const track = (socket: Duplex): void => {
        open.add(socket)
        socket.on('error', () => socket.destroy())
        socket.once('close', () => open.delete(socket))
    }
    terminated.on('clientError', (_error, socket) => socket.destroy())

    server.on('connect', (req: http.IncomingMessage, client: Duplex, head: Buffer) => {
        track(client)
        const target = targetOf(req.url)
        if (!target) {
            client.end('HTTP/1.1 400 Bad Request\r\n\r\n')
            return
        }
        const leaf = leaves.get(target.host)
        if (leaf) {
            client.unshift(head)
            client.write(ESTABLISHED)
            const secure = new tls.TLSSocket(client, { isServer: true, key: leaf.key, cert: leaf.cert })
            track(secure)
            terminated.emit('connection', secure)
            return
        }
        const upstream = net.connect(target.port, target.host)
        let established = false
        upstream.once('error', () => (established ? client.destroy() : client.end('HTTP/1.1 502 Bad Gateway\r\n\r\n')))
        track(upstream)
        upstream.once('connect', () => {
            established = true
            client.write(ESTABLISHED)
            upstream.write(head)
            upstream.pipe(client)
            client.pipe(upstream)
        })
        client.once('close', () => upstream.destroy())
    })

    return {
        close: () => {
            open.forEach((socket) => socket.destroy())
            terminated.closeAllConnections()
        },
    }
}
