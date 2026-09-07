import dnsPromises from 'dns/promises'
import http from 'node:http'
import http2 from 'node:http2'
import https from 'node:https'
import net, { AddressInfo } from 'node:net'
import tls from 'node:tls'

import { TestTlsIdentity, createTestTlsIdentity } from '~/tests/helpers/tls'

type RequestModule = typeof import('./request')
type AnyServer = http.Server | http2.Http2SecureServer | https.Server

const proxyEnvironmentNames = ['HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy'] as const
const ORIGIN_HOST = 'origin.test'
const keepAliveTimeoutMs = 1000

function serverPort(server: AnyServer): number {
    return (server.address() as AddressInfo).port
}

function listen(server: AnyServer): Promise<void> {
    return new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
}

function close(server: AnyServer): Promise<void> {
    if (!server.listening) {
        return Promise.resolve()
    }
    return new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())))
}

async function waitFor(condition: () => boolean, timeoutMs: number): Promise<void> {
    const deadline = Date.now() + timeoutMs
    while (!condition()) {
        if (Date.now() > deadline) {
            throw new Error('condition not met in time')
        }
        await new Promise((resolve) => setTimeout(resolve, 25))
    }
}

/** An HTTP/2 origin that counts sessions and streams, pings its client, and can hold responses. */
class Http2Origin {
    public readonly server: http2.Http2SecureServer
    public readonly sessions: Array<{ session: http2.ServerHttp2Session; streams: number; open: boolean }> = []
    public readonly served = new Map<string, number>()
    public inFlight = 0
    public maxInFlight = 0
    private readonly pending: Array<() => void> = []
    private readonly pings = new Set<NodeJS.Timeout>()

    constructor(
        identity: TestTlsIdentity,
        private readonly respond: (url: string, finish: () => void, origin: Http2Origin) => void,
        settings: http2.Settings = {}
    ) {
        this.server = http2.createSecureServer({
            allowHTTP1: true,
            cert: identity.certificate,
            key: identity.privateKey,
            settings,
        })
        this.server.on('session', (session) => {
            const entry = { session, streams: 0, open: true }
            this.sessions.push(entry)
            session.on('stream', () => entry.streams++)
            const ping = setInterval(() => session.ping(() => {}), 100)
            this.pings.add(ping)
            session.once('close', () => {
                entry.open = false
                clearInterval(ping)
                this.pings.delete(ping)
            })
        })
        this.server.on('request', (request, response) => {
            const url = request.url ?? ''
            this.served.set(url, (this.served.get(url) ?? 0) + 1)
            this.inFlight++
            this.maxInFlight = Math.max(this.maxInFlight, this.inFlight)
            const finish = (): void => {
                this.inFlight--
                response.writeHead(200, { 'content-type': 'text/plain', 'x-http-version': request.httpVersion })
                response.end(url)
            }
            this.respond(url, finish, this)
        })
    }

    public get openSessions(): number {
        return this.sessions.filter((entry) => entry.open).length
    }

    public holdUntil(count: number, finish: () => void): void {
        this.pending.push(finish)
        if (this.pending.length === count) {
            this.pending.splice(0).forEach((release) => release())
        }
    }

    public async stop(): Promise<void> {
        for (const ping of this.pings) {
            clearInterval(ping)
        }
        for (const entry of this.sessions) {
            entry.session.destroy()
        }
        await close(this.server)
    }
}

describe.each([['CONNECT proxy'], ['direct connection']])('secure HTTP/2 requests over a %s', (mode) => {
    const viaProxy = mode === 'CONNECT proxy'
    let requestModule: RequestModule
    let identity: TestTlsIdentity
    let origin: Http2Origin
    let http1Origin: https.Server
    let connectProxy: http.Server
    let tlsConnectSpy: jest.SpyInstance
    let lookupSpy: jest.SpyInstance | undefined
    const originalExternalRequestConnections = process.env.EXTERNAL_REQUEST_CONNECTIONS
    const originalKeepAliveTimeout = process.env.EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS
    const originalProxyEnvironment = Object.fromEntries(
        proxyEnvironmentNames.map((name) => [name, process.env[name]])
    ) as Record<(typeof proxyEnvironmentNames)[number], string | undefined>
    const http1OriginProtocols: string[] = []
    const proxyAuthorities: string[] = []
    const openSockets = new Set<net.Socket>()
    const extraOrigins: Http2Origin[] = []

    const originUrl = (target: Http2Origin): string => `https://${ORIGIN_HOST}:${serverPort(target.server)}`

    const fetchText = async (url: string, options: { http2IdleTimeoutMs?: number } = {}): Promise<string> => {
        const response = await requestModule.fetchStreamed(url, { allowH2: true, timeoutMs: 5000, ...options })
        return (await response.read(100)).bytes.toString()
    }

    beforeAll(async () => {
        identity = await createTestTlsIdentity(ORIGIN_HOST)
        origin = new Http2Origin(identity, (url, finish) => {
            if (url === '/slow') {
                setTimeout(finish, keepAliveTimeoutMs * 1.5)
                return
            }
            finish()
        })
        await listen(origin.server)

        http1Origin = https.createServer(
            { cert: identity.certificate, key: identity.privateKey },
            (request, response) => {
                http1OriginProtocols.push(request.httpVersion)
                response.writeHead(200, { 'content-type': 'text/plain' })
                response.end(request.url)
            }
        )
        await listen(http1Origin)

        connectProxy = http.createServer()
        connectProxy.on('connection', (socket) => {
            openSockets.add(socket)
            socket.once('close', () => openSockets.delete(socket))
        })
        connectProxy.on('connect', (request, clientSocket, head) => {
            proxyAuthorities.push(request.url ?? '')
            const requestedPort = Number(request.url?.split(':').at(-1))
            const originSocket = net.connect(requestedPort, '127.0.0.1', () => {
                clientSocket.write('HTTP/1.1 200 Connection Established\r\n\r\n')
                if (head.length > 0) {
                    originSocket.write(head)
                }
                clientSocket.pipe(originSocket)
                originSocket.pipe(clientSocket)
            })
            openSockets.add(originSocket)
            originSocket.once('close', () => openSockets.delete(originSocket))
            originSocket.once('error', () => clientSocket.destroy())
            clientSocket.once('error', () => originSocket.destroy())
        })
        await listen(connectProxy)

        const connectWithSystemTrust = tls.connect
        tlsConnectSpy = jest
            .spyOn(tls, 'connect')
            .mockImplementation(((options: tls.ConnectionOptions, callback?: () => void) =>
                connectWithSystemTrust({ ...options, ca: identity.certificate }, callback)) as typeof tls.connect)
        for (const name of proxyEnvironmentNames) {
            delete process.env[name]
        }
        if (viaProxy) {
            process.env.HTTPS_PROXY = `http://127.0.0.1:${serverPort(connectProxy)}`
        } else {
            const realLookup = dnsPromises.lookup
            lookupSpy = jest
                .spyOn(dnsPromises, 'lookup')
                .mockImplementation(((hostname: string, options: unknown) =>
                    hostname === ORIGIN_HOST
                        ? Promise.resolve([{ address: '127.0.0.1', family: 4 }])
                        : (realLookup as (h: string, o: unknown) => Promise<unknown>)(hostname, options)) as never)
        }
        process.env.EXTERNAL_REQUEST_CONNECTIONS = '4'
        process.env.EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS = String(keepAliveTimeoutMs)

        jest.resetModules()
        requestModule = require('./request') as RequestModule
    })

    afterAll(async () => {
        for (const name of proxyEnvironmentNames) {
            const value = originalProxyEnvironment[name]
            if (value === undefined) {
                delete process.env[name]
            } else {
                process.env[name] = value
            }
        }
        if (originalExternalRequestConnections === undefined) {
            delete process.env.EXTERNAL_REQUEST_CONNECTIONS
        } else {
            process.env.EXTERNAL_REQUEST_CONNECTIONS = originalExternalRequestConnections
        }
        if (originalKeepAliveTimeout === undefined) {
            delete process.env.EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS
        } else {
            process.env.EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS = originalKeepAliveTimeout
        }
        tlsConnectSpy.mockRestore()
        lookupSpy?.mockRestore()

        for (const socket of openSockets) {
            socket.destroy()
        }
        http1Origin.closeAllConnections()
        connectProxy.closeAllConnections()
        await Promise.all([
            origin.stop(),
            ...extraOrigins.map((extra) => extra.stop()),
            close(http1Origin),
            close(connectProxy),
        ])
        await identity.cleanup()
    })

    const startOrigin = async (
        respond: (url: string, finish: () => void, target: Http2Origin) => void,
        settings: http2.Settings = {}
    ): Promise<Http2Origin> => {
        const extra = new Http2Origin(identity, respond, settings)
        extraOrigins.push(extra)
        await listen(extra.server)
        return extra
    }

    it('negotiates, multiplexes, defaults to HTTP/1.1, and falls back to an HTTP/1.1 origin', async () => {
        const url = originUrl(origin)
        const bufferedResponse = await requestModule.fetch(`${url}/buffered`, { allowH2: true, timeoutMs: 2000 })
        expect(await bufferedResponse.text()).toBe('/buffered')
        expect(await fetchText(`${url}/streamed`)).toBe('/streamed')

        const concurrent = await Promise.all(
            ['/concurrent-a', '/concurrent-b'].map((path) => fetchText(`${url}${path}`))
        )
        expect(concurrent).toEqual(['/concurrent-a', '/concurrent-b'])

        const defaultResponse = await requestModule.fetchStreamed(`${url}/default`, { timeoutMs: 2000 })
        expect(defaultResponse.headers['x-http-version']).toBe('1.1')
        expect((await defaultResponse.read(100)).bytes.toString()).toBe('/default')

        const fallbackUrl = `https://${ORIGIN_HOST}:${serverPort(http1Origin)}/fallback`
        expect(await fetchText(fallbackUrl)).toBe('/fallback')

        expect(origin.sessions.map((entry) => entry.streams)).toEqual([4])
        expect(http1OriginProtocols).toEqual(['1.1'])
        if (viaProxy) {
            const http2Authority = `${ORIGIN_HOST}:${serverPort(origin.server)}`
            expect(proxyAuthorities).toEqual([
                http2Authority,
                http2Authority,
                `${ORIGIN_HOST}:${serverPort(http1Origin)}`,
            ])
        }
    }, 10000)

    it('carries a burst to a cold origin on one session', async () => {
        const cold = await startOrigin((url, finish, target) => target.holdUntil(6, finish))
        const paths = Array.from({ length: 6 }, (_, index) => `/burst-${index}`)

        const bodies = await Promise.all(paths.map((path) => fetchText(`${originUrl(cold)}${path}`)))

        expect(bodies).toEqual(paths)
        expect(cold.sessions.map((entry) => entry.streams)).toEqual([6])
    }, 10000)

    it('stays within the stream limit the origin advertises', async () => {
        const limited = await startOrigin((url, finish) => setTimeout(finish, 100), { maxConcurrentStreams: 3 })
        const paths = Array.from({ length: 8 }, (_, index) => `/limited-${index}`)

        const bodies = await Promise.all(paths.map((path) => fetchText(`${originUrl(limited)}${path}`)))

        expect(bodies).toEqual(paths)
        expect(limited.maxInFlight).toBe(3)
        expect([...limited.served.values()]).toEqual(paths.map(() => 1))
        expect(limited.sessions).toHaveLength(1)
    }, 10000)

    it('closes an idle session after the keep-alive timeout despite pings, but not one with a slow response in flight', async () => {
        const url = originUrl(origin)
        expect(await fetchText(`${url}/slow`)).toBe('/slow')
        const sessionsBefore = origin.sessions.length

        await waitFor(() => origin.openSessions === 0, keepAliveTimeoutMs * 3)

        expect(await fetchText(`${url}/after-idle`)).toBe('/after-idle')
        expect(origin.sessions).toHaveLength(sessionsBefore + 1)
        expect(origin.openSessions).toBe(1)
    }, 15000)

    it('keeps a session open for the idle timeout a caller asks for', async () => {
        const patient = await startOrigin((url, finish) => finish())

        expect(await fetchText(`${originUrl(patient)}/patient`, { http2IdleTimeoutMs: 60_000 })).toBe('/patient')
        await new Promise((resolve) => setTimeout(resolve, keepAliveTimeoutMs * 2))

        expect(patient.openSessions).toBe(1)
    }, 10000)
})
