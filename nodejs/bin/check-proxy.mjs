import net from 'node:net'

import { checkHttp } from './liveness-http.mjs'

export function checkProxyListener({ port = 4750, timeoutMs = 2000 } = {}) {
    return new Promise((resolve) => {
        const socket = net.createConnection({ host: '127.0.0.1', port })
        const finish = (healthy) => {
            clearTimeout(deadline)
            socket.destroy()
            resolve(healthy)
        }
        const deadline = setTimeout(() => finish(false), timeoutMs)
        socket.once('connect', () => finish(true))
        socket.once('error', () => finish(false))
    })
}

export async function checkProxy({ proxyPort = 4750, metricsPort = 9810, timeoutMs = 2000 } = {}) {
    const [listener, metrics] = await Promise.all([
        checkProxyListener({ port: proxyPort, timeoutMs }),
        checkHttp({
            port: metricsPort,
            path: '/metrics',
            timeoutMs,
            validateBody: (body, headers) =>
                headers['content-type']?.split(';')[0].trim() === 'text/plain' &&
                /^go_goroutines [0-9]+\r?$/m.test(body),
        }),
    ])
    return { listener, metrics }
}
