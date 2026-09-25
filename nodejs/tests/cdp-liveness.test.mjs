import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import { EventEmitter } from 'node:events'
import http from 'node:http'
import net from 'node:net'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { checkProxy, checkProxyListener } from '../bin/check-proxy.mjs'
import { checkHttp } from '../bin/liveness-http.mjs'

const entrypoint = fileURLToPath(new URL('../bin/check-cdp-liveness.mjs', import.meta.url))
const metrics = '# HELP go_goroutines Number of goroutines.\n# TYPE go_goroutines gauge\ngo_goroutines 8\n'

async function listen(context, server, port = 0) {
    const sockets = new Set()
    server.on('connection', (socket) => {
        sockets.add(socket)
        socket.on('close', () => sockets.delete(socket))
    })
    context.after(async () => {
        for (const socket of sockets) {
            socket.destroy()
        }
        if (server.listening) {
            await new Promise((resolve) => server.close(resolve))
        }
    })
    await new Promise((resolve, reject) => {
        server.once('error', reject)
        server.listen(port, '127.0.0.1', () => {
            server.off('error', reject)
            resolve()
        })
    })
    return server.address().port
}

async function application(context, status = 200, port = 0) {
    return listen(
        context,
        http.createServer((request, response) => {
            assert.equal(request.url, '/_health')
            response.writeHead(status, { 'Content-Type': 'application/json' })
            response.end(JSON.stringify({ status: status === 200 ? 'ok' : 'error', checks: { consumer: 'ok' } }))
        }),
        port
    )
}

async function sidecar(context, { handler, proxy = true } = {}) {
    const listener = net.createServer((socket) => socket.end())
    if (proxy) {
        await listen(context, listener, 4750)
    }
    await listen(
        context,
        http.createServer(
            handler ??
                ((request, response) => {
                    assert.equal(request.url, '/metrics')
                    response.writeHead(200, { 'Content-Type': 'text/plain; version=0.0.4' })
                    response.end(metrics)
                })
        ),
        9810
    )
    return listener
}

async function probe(port, args = ['--proxy-sidecar'], env = {}) {
    const direct = process.env.LIVENESS_TEST_DIRECT_EXEC === '1'
    return new Promise((resolve, reject) => {
        execFile(
            direct ? entrypoint : process.execPath,
            direct ? args : [entrypoint, ...args],
            {
                timeout: 4500,
                env: { ...process.env, HTTP_SERVER_PORT: String(port), ...env },
            },
            (error, stdout, stderr) => {
                if (error && (error.killed || error.signal || typeof error.code !== 'number')) {
                    reject(error)
                    return
                }
                resolve({ code: error?.code ?? 0, stdout, stderr })
            }
        )
    })
}

test('both checks pass without a shell, DNS, or proxy environment support', async (context) => {
    const port = await application(context)
    await sidecar(context)
    assert.deepEqual(
        await probe(port, ['--proxy-sidecar'], {
            PATH: '/does-not-exist',
            HTTP_PROXY: 'http://proxy.invalid:1',
            HTTPS_PROXY: 'http://proxy.invalid:1',
            http_proxy: 'http://proxy.invalid:1',
            https_proxy: 'http://proxy.invalid:1',
            NO_PROXY: '',
            no_proxy: '',
            NODE_USE_ENV_PROXY: '1',
        }),
        { code: 0, stdout: '', stderr: '' }
    )
})

for (const mode of ['central', 'disabled']) {
    for (const status of [200, 503]) {
        test(`${mode} mode keeps the application result (${status}) without local sidecar checks`, async (context) => {
            const port = await application(context, status)
            let sidecarRequests = 0
            await sidecar(context, {
                handler: (_request, response) => {
                    sidecarRequests++
                    response.writeHead(503).end()
                },
            })
            const proxy = mode === 'central' ? 'http://proxy.invalid:4750' : ''
            const result = await probe(port, [], { HTTP_PROXY: proxy, HTTPS_PROXY: proxy })
            assert.equal(result.code, status === 200 ? 0 : 1)
            assert.equal(sidecarRequests, 0)
            assert.doesNotMatch(result.stderr, /proxy/)
        })
    }
}

test('the default application port is 6738', async (context) => {
    await application(context, 200, 6738)
    assert.equal((await probe(6738, [], { HTTP_SERVER_PORT: undefined })).code, 0)
})

test('application failure cannot be hidden by a healthy sidecar', async (context) => {
    const port = await application(context, 503)
    await sidecar(context)
    assert.deepEqual(await probe(port), {
        code: 1,
        stdout: '',
        stderr: 'CDP liveness: application check failed\n',
    })
})

test('application connection refusal fails', async (context) => {
    const server = net.createServer()
    const port = await listen(context, server)
    await new Promise((resolve) => server.close(resolve))
    assert.equal((await probe(port, [])).code, 1)
})

test('a healthy metrics endpoint cannot hide proxy refusal', async (context) => {
    const port = await application(context)
    await sidecar(context, { proxy: false })
    assert.deepEqual(await probe(port), {
        code: 1,
        stdout: '',
        stderr: 'CDP liveness: proxy listener check failed\n',
    })
})

test('a healthy proxy listener cannot hide metrics refusal', async (context) => {
    const port = await application(context)
    await listen(
        context,
        net.createServer((socket) => socket.end()),
        4750
    )
    assert.deepEqual(await probe(port), {
        code: 1,
        stdout: '',
        stderr: 'CDP liveness: proxy metrics check failed\n',
    })
})

for (const [name, status, body, contentType] of [
    ['HTTP failure', 503, metrics, 'text/plain'],
    ['redirect', 302, metrics, 'text/plain'],
    ['empty body', 200, '', 'text/plain'],
    ['HTML body', 200, '<html>ok</html>', 'text/html'],
    ['invalid metric', 200, 'go_goroutines not-a-number\n', 'text/plain'],
    ['wrong content type', 200, metrics, 'application/json'],
    ['large body', 200, metrics + 'x'.repeat(1024 * 1024), 'text/plain'],
]) {
    test(`metrics ${name} fails without printing the response`, async (context) => {
        const port = await application(context)
        await sidecar(context, {
            handler: (_request, response) => {
                response.writeHead(status, { 'Content-Type': contentType }).end(body)
            },
        })
        assert.deepEqual(await probe(port), {
            code: 1,
            stdout: '',
            stderr: 'CDP liveness: proxy metrics check failed\n',
        })
    })
}

test('invalid HTTP fails', async (context) => {
    const port = await listen(
        context,
        net.createServer((socket) => socket.end('not HTTP\r\n\r\n'))
    )
    assert.equal(await checkHttp({ port, path: '/metrics' }), false)
})

test('a truncated metrics response fails', async (context) => {
    const metricsPort = await listen(
        context,
        net.createServer((socket) => {
            socket.once('data', () => {
                socket.end(
                    'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 999\r\n\r\ngo_goroutines 8\n'
                )
            })
        })
    )
    const proxyPort = await listen(
        context,
        net.createServer((socket) => socket.end())
    )
    assert.deepEqual(await checkProxy({ metricsPort, proxyPort }), { listener: true, metrics: false })
})

test('application and metrics deadlines run concurrently below the probe timeout', async (context) => {
    const port = await listen(
        context,
        http.createServer(() => {})
    )
    await sidecar(context, { handler: () => {} })
    const start = performance.now()
    const result = await probe(port)
    assert.equal(result.code, 1)
    assert.match(result.stderr, /application check failed/)
    assert.match(result.stderr, /proxy metrics check failed/)
    assert.ok(performance.now() - start < 4000)
})

test('a slow metrics body does not extend the deadline', async (context) => {
    await sidecar(context, {
        handler: (_request, response) => {
            response.writeHead(200, { 'Content-Type': 'text/plain' })
            response.write(metrics)
            const interval = setInterval(() => response.write('# waiting\n'), 10)
            response.on('close', () => clearInterval(interval))
        },
    })
    const start = performance.now()
    assert.deepEqual(await checkProxy({ timeoutMs: 100 }), { listener: true, metrics: false })
    assert.ok(performance.now() - start < 1000)
})

test('a proxy connect timeout destroys the socket', async (context) => {
    const socket = new EventEmitter()
    let destroyed = false
    socket.destroy = () => {
        destroyed = true
    }
    context.mock.method(net, 'createConnection', () => socket)
    assert.equal(await checkProxyListener({ timeoutMs: 20 }), false)
    assert.equal(destroyed, true)
})

test('repeated probes fail during a sustained outage and recover after the listener returns', async (context) => {
    const port = await application(context)
    const listener = await sidecar(context)
    assert.equal((await probe(port)).code, 0)
    await new Promise((resolve) => listener.close(resolve))
    for (let attempt = 0; attempt < 3; attempt++) {
        assert.equal((await probe(port)).code, 1)
    }
    await new Promise((resolve) => listener.listen(4750, '127.0.0.1', resolve))
    assert.equal((await probe(port)).code, 0)
})

test('a brief listener restart between samples is not recorded as a failure', async (context) => {
    const port = await application(context)
    const listener = await sidecar(context)
    assert.equal((await probe(port)).code, 0)
    await new Promise((resolve) => listener.close(resolve))
    await new Promise((resolve) => listener.listen(4750, '127.0.0.1', resolve))
    assert.equal((await probe(port)).code, 0)
})

test('invalid settings fail without printing their values', async () => {
    for (const port of ['', '0', '-1', '65536', 'NaN', 'sensitive-value']) {
        assert.deepEqual(await probe(port, []), {
            code: 1,
            stdout: '',
            stderr: 'CDP liveness: invalid arguments or HTTP_SERVER_PORT\n',
        })
    }
    assert.equal((await probe(6738, ['--unknown'])).code, 1)
})
