import http from 'node:http'
import http2 from 'node:http2'
import https from 'node:https'
import net, { AddressInfo } from 'node:net'
import tls from 'node:tls'

import { TestTlsIdentity, createTestTlsIdentity } from '~/tests/helpers/tls'

type RequestModule = typeof import('./request')

const proxyEnvironmentNames = ['HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy'] as const

function serverPort(server: http.Server | http2.Http2SecureServer | https.Server): number {
    return (server.address() as AddressInfo).port
}

function listen(server: http.Server | http2.Http2SecureServer | https.Server): Promise<void> {
    return new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
}

function close(server: http.Server | http2.Http2SecureServer | https.Server): Promise<void> {
    if (!server.listening) {
        return Promise.resolve()
    }
    return new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())))
}

describe('secure HTTP/2 requests', () => {
    let requestModule: RequestModule
    let http2Origin: http2.Http2SecureServer
    let http1Origin: https.Server
    let connectProxy: http.Server
    let tlsConnectSpy: jest.SpyInstance
    let tlsIdentity: TestTlsIdentity | undefined
    const originalExternalRequestConnections = process.env.EXTERNAL_REQUEST_CONNECTIONS
    const originalProxyEnvironment = Object.fromEntries(
        proxyEnvironmentNames.map((name) => [name, process.env[name]])
    ) as Record<(typeof proxyEnvironmentNames)[number], string | undefined>
    let http2SessionCount = 0
    const http2OriginProtocols: string[] = []
    const http1OriginProtocols: string[] = []
    const proxyAuthorities: string[] = []
    const openSockets = new Set<net.Socket>()
    const openHttp2Sessions = new Set<http2.ServerHttp2Session>()
    const pendingConcurrentResponses: Array<() => void> = []

    beforeAll(async () => {
        const generatedTlsIdentity = await createTestTlsIdentity('origin.test')
        tlsIdentity = generatedTlsIdentity

        http2Origin = http2.createSecureServer({
            allowHTTP1: true,
            cert: generatedTlsIdentity.certificate,
            key: generatedTlsIdentity.privateKey,
        })
        http2Origin.on('request', (request, response) => {
            http2OriginProtocols.push(request.httpVersion)
            const finishResponse = (): void => {
                response.writeHead(200, { 'content-type': 'text/plain' })
                response.end(request.url)
            }
            if (request.url?.startsWith('/concurrent-')) {
                pendingConcurrentResponses.push(finishResponse)
                if (pendingConcurrentResponses.length === 2) {
                    pendingConcurrentResponses.splice(0).forEach((finish) => finish())
                }
                return
            }
            finishResponse()
        })
        http2Origin.on('session', (session) => {
            http2SessionCount += 1
            openHttp2Sessions.add(session)
            session.once('close', () => openHttp2Sessions.delete(session))
        })
        await listen(http2Origin)

        http1Origin = https.createServer(
            { cert: generatedTlsIdentity.certificate, key: generatedTlsIdentity.privateKey },
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
                connectWithSystemTrust(
                    { ...options, ca: generatedTlsIdentity.certificate },
                    callback
                )) as typeof tls.connect)
        process.env.HTTPS_PROXY = `http://127.0.0.1:${serverPort(connectProxy)}`
        process.env.EXTERNAL_REQUEST_CONNECTIONS = '2'
        delete process.env.HTTP_PROXY
        delete process.env.https_proxy
        delete process.env.http_proxy

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
        tlsConnectSpy.mockRestore()

        for (const session of openHttp2Sessions) {
            session.destroy()
        }
        for (const socket of openSockets) {
            socket.destroy()
        }
        http1Origin.closeAllConnections()
        connectProxy.closeAllConnections()
        await Promise.all([close(http2Origin), close(http1Origin), close(connectProxy)])
        await tlsIdentity?.cleanup()
    })

    it('negotiates, reuses, runs concurrently, defaults, and falls back through a CONNECT proxy', async () => {
        const http2Authority = `origin.test:${serverPort(http2Origin)}`
        const http2Url = `https://${http2Authority}`
        const bufferedResponse = await requestModule.fetch(`${http2Url}/buffered`, { allowH2: true, timeoutMs: 2000 })
        expect(await bufferedResponse.text()).toBe('/buffered')

        const streamedResponse = await requestModule.fetchStreamed(`${http2Url}/streamed`, {
            allowH2: true,
            timeoutMs: 2000,
        })
        expect((await streamedResponse.read(100)).bytes.toString()).toBe('/streamed')

        const concurrentBodies = await Promise.all(
            ['/concurrent-a', '/concurrent-b'].map(async (path) => {
                const response = await requestModule.fetchStreamed(`${http2Url}${path}`, {
                    allowH2: true,
                    timeoutMs: 2000,
                })
                return (await response.read(100)).bytes.toString()
            })
        )
        expect(concurrentBodies).toEqual(['/concurrent-a', '/concurrent-b'])

        const defaultResponse = await requestModule.fetchStreamed(`${http2Url}/default`, { timeoutMs: 2000 })
        expect((await defaultResponse.read(100)).bytes.toString()).toBe('/default')

        const http1Authority = `origin.test:${serverPort(http1Origin)}`
        const fallbackResponse = await requestModule.fetchStreamed(`https://${http1Authority}/fallback`, {
            allowH2: true,
            timeoutMs: 2000,
        })
        expect((await fallbackResponse.read(100)).bytes.toString()).toBe('/fallback')

        expect(http2OriginProtocols).toEqual(['2.0', '2.0', '2.0', '2.0', '1.1'])
        expect(http1OriginProtocols).toEqual(['1.1'])
        expect(http2SessionCount).toBe(2)
        expect(proxyAuthorities).toEqual([http2Authority, http2Authority, http2Authority, http1Authority])
    }, 10000)
})
