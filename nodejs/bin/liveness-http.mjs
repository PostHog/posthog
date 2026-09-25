import http from 'node:http'

export function checkHttp({ port, path, timeoutMs = 2000, validateBody }) {
    return new Promise((resolve) => {
        let response
        let settled = false
        const finish = (healthy) => {
            if (settled) {
                return
            }
            settled = true
            clearTimeout(deadline)
            response?.destroy()
            request.destroy()
            resolve(healthy)
        }
        const request = http.get({
            hostname: '127.0.0.1',
            port,
            path,
            agent: false,
            headers: { Accept: 'text/plain; version=0.0.4' },
        })
        const deadline = setTimeout(() => finish(false), timeoutMs)
        request.on('error', () => finish(false))
        request.on('response', (incoming) => {
            response = incoming
            if (incoming.statusCode !== 200) {
                finish(false)
                return
            }
            if (!validateBody) {
                finish(true)
                return
            }
            let size = 0
            const chunks = []
            incoming.on('error', () => finish(false))
            incoming.on('aborted', () => finish(false))
            incoming.on('data', (chunk) => {
                size += chunk.length
                if (size > 1024 * 1024) {
                    finish(false)
                    return
                }
                chunks.push(chunk)
            })
            incoming.on('end', () => {
                finish(incoming.complete && validateBody(Buffer.concat(chunks).toString('utf8'), incoming.headers))
            })
        })
    })
}
