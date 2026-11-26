import { LookupAnswer, lookupAnswers, loopbackAddresses } from '~/tests/helpers/mocks/dns.mock'

import http, { Agent, ClientRequest, IncomingMessage, RequestListener, ServerResponse, createServer } from 'node:http'
import https, { createServer as createTlsServer } from 'node:https'
import { AddressInfo, Server, Socket } from 'node:net'
import tls from 'node:tls'
import { register } from 'prom-client'

import { ENDPOINT_THAT_REFUSES_CONNECTIONS, attachmentFile, sesTransportFor } from '~/cdp/_tests/email-delivery-fakes'

import { SesTransport } from './ses-transport'

const SDK_SOCKETS_PER_HOST = 50

const LOOPBACK_ONLY_TEST_KEY = `-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg42UWsxxJds3SJDeC
AMRVtNlqcPSxMOchAOwgC897cSehRANCAASvBCS7ojKBc0PRjxZEpA16wbZ45nP4
3tS4NtsPUVlajkZ84lHSGIQFzg5z72Eok/L5JyKeUf52eQ5umCTS/PKe
-----END PRIVATE KEY-----`

const LOOPBACK_ONLY_TEST_CERT = `-----BEGIN CERTIFICATE-----
MIIBjzCCATagAwIBAgIUYB/tygavSvNw1GXsN7EIl/nctyYwCgYIKoZIzj0EAwIw
FDESMBAGA1UEAwwJMTI3LjAuMC4xMCAXDTI2MTEyNjE2NTI1N1oYDzIxMjYxMTAy
MTY1MjU3WjAUMRIwEAYDVQQDDAkxMjcuMC4wLjEwWTATBgcqhkjOPQIBBggqhkjO
PQMBBwNCAASvBCS7ojKBc0PRjxZEpA16wbZ45nP43tS4NtsPUVlajkZ84lHSGIQF
zg5z72Eok/L5JyKeUf52eQ5umCTS/PKeo2QwYjAdBgNVHQ4EFgQU8JgOY9YzavZD
FgNhclc3Wbdzpd0wHwYDVR0jBBgwFoAU8JgOY9YzavZDFgNhclc3Wbdzpd0wDwYD
VR0TAQH/BAUwAwEB/zAPBgNVHREECDAGhwR/AAABMAoGCCqGSM49BAMCA0cAMEQC
IE7tbd9QvrxwRqXkvGBtmzZQZEAkBCwM3Tx1CgVLU9/DAiBQX6RNJlE7MnGYdv/c
qBUv5b+0DMLCHJZPCbZrNpcwuQ==
-----END CERTIFICATE-----`

const peerFor = {
    http: (listener: RequestListener): Server => createServer(listener),
    https: (listener: RequestListener): Server =>
        createTlsServer({ key: LOOPBACK_ONLY_TEST_KEY, cert: LOOPBACK_ONLY_TEST_CERT }, listener),
}

const trustTheTestCert = (): void => {
    const connect = tls.connect.bind(tls) as (options: tls.ConnectionOptions) => tls.TLSSocket
    jest.spyOn(tls, 'connect').mockImplementation(((options: tls.ConnectionOptions) =>
        connect({ ...options, ca: LOOPBACK_ONLY_TEST_CERT })) as typeof tls.connect)
}

const answerAccepted = (response: ServerResponse, messageId: string): void => {
    response.writeHead(200, { 'content-type': 'application/json' }).end(`{"MessageId":"${messageId}"}`)
}

const email = {
    FromEmailAddress: 'sender@example.com',
    Destination: { ToAddresses: ['recipient@example.com'] },
    Content: { Simple: { Subject: { Data: 'Report' }, Body: { Text: { Data: 'Attached.' } } } },
}
const { metadata, bytes } = attachmentFile({ filename: 'report.pdf', contentType: 'application/pdf' })
const files = [{ file: metadata, bytes }]
const withFiles = { email, files, deadline: new AbortController().signal }

async function metricValue(name: string, labels: Record<string, string>): Promise<number> {
    const metric = await register.getSingleMetric(name)!.get()
    const sample = metric.values.find((value) =>
        Object.entries(labels).every(([key, labelValue]) => value.labels[key] === labelValue)
    )
    return sample?.value ?? 0
}

const notFound: LookupAnswer = (_options, callback) =>
    callback(
        Object.assign(new Error('getaddrinfo ENOTFOUND ses.invalid'), {
            code: 'ENOTFOUND',
            syscall: 'getaddrinfo',
            hostname: 'ses.invalid',
        })
    )

const networkUnreachable: LookupAnswer = (_options, callback) =>
    callback(
        Object.assign(new Error('connect ENETUNREACH 192.0.2.1:443'), {
            code: 'ENETUNREACH',
            syscall: 'connect',
            address: '192.0.2.1',
            port: 443,
        })
    )

type RetryToken = { getRetryCount: () => number; getRetryDelay: () => number }

const retriesTwice = {
    acquireInitialRetryToken: (): Promise<RetryToken> => Promise.resolve(retryToken(0)),
    refreshRetryTokenForRetry: (token: RetryToken): Promise<RetryToken> =>
        token.getRetryCount() < 2
            ? Promise.resolve(retryToken(token.getRetryCount() + 1))
            : Promise.reject(new Error('no retries left')),
    recordSuccess: () => {},
}

function retryToken(retryCount: number): RetryToken {
    return { getRetryCount: () => retryCount, getRetryDelay: () => 0 }
}

const watchRequests = (protocol: keyof typeof peerFor, onRequest: (request: ClientRequest) => void): void => {
    const client = protocol === 'https' ? https : http
    const request = client.request as (...args: unknown[]) => ClientRequest
    jest.spyOn(client, 'request').mockImplementation(((...args: unknown[]) => {
        const created = request(...args)
        onRequest(created)
        return created
    }) as typeof client.request)
}

const queuedForASocket = (request: ClientRequest): number =>
    Object.values((request as ClientRequest & { agent: Agent }).agent.requests).reduce(
        (queued, queue) => queued + (queue?.length ?? 0),
        0
    )

describe('SesTransport', () => {
    let transport: SesTransport | undefined
    let peer: Server | undefined
    const peerSockets = new Set<Socket>()

    const listen = async (server: Server): Promise<number> => {
        peer = server
        server.on('connection', (socket: Socket) => {
            peerSockets.add(socket)
            socket.on('close', () => peerSockets.delete(socket))
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        return (server.address() as AddressInfo).port
    }

    afterEach(async () => {
        transport?.destroy()
        transport = undefined
        peerSockets.forEach((socket) => socket.destroy())
        await new Promise<void>((resolve) => (peer ? peer.close(() => resolve()) : resolve()))
        peer = undefined
        jest.restoreAllMocks()
    })

    const sesPeer = async (
        protocol: keyof typeof peerFor,
        onRequest: (request: IncomingMessage, response: ServerResponse) => void
    ): Promise<{ endpoint: string; connections: Set<Socket> }> => {
        if (protocol === 'https') {
            trustTheTestCert()
        }
        const connections = new Set<Socket>()
        const port = await listen(
            peerFor[protocol]((request, response) => {
                connections.add(request.socket)
                request.resume()
                request.on('end', () => onRequest(request, response))
            })
        )
        return { endpoint: `${protocol}://127.0.0.1:${port}`, connections }
    }

    it.each(['http', 'https'] as const)(
        'over %s, opens a connection for each email with files in flight, also past the sockets the SDK keeps per host',
        async (protocol) => {
            const inFlight = SDK_SOCKETS_PER_HOST + 1
            const held: ServerResponse[] = []
            const ses = await sesPeer(protocol, (_request, response) => {
                held.push(response)
                if (held.length === inFlight) {
                    held.forEach((answer, index) => answerAccepted(answer, `m-${index}`))
                }
            })
            const deadline = new AbortController()
            let created = 0
            let queued = 0
            watchRequests(protocol, (request) => {
                if (++created === inFlight) {
                    queued = queuedForASocket(request)
                    if (queued > 0) {
                        setImmediate(() => deadline.abort())
                    }
                }
            })
            transport = sesTransportFor({ endpoint: ses.endpoint })

            const outcomes = await Promise.all(
                Array.from({ length: inFlight }, () => transport!.send({ email, files, deadline: deadline.signal }))
            )

            expect({
                queued,
                accepted: outcomes.filter(({ kind }) => kind === 'accepted').length,
                connections: ses.connections.size,
            }).toEqual({ queued: 0, accepted: inFlight, connections: inFlight })
        }
    )

    it.each(['http', 'https'] as const)(
        'over %s, sends each email with files on a new connection, also after the last send closed',
        async (protocol) => {
            let answered = 0
            const ses = await sesPeer(protocol, (_request, response) => answerAccepted(response, `m-${++answered}`))
            transport = sesTransportFor({ endpoint: ses.endpoint })

            const first = await transport.send(withFiles)
            const second = await transport.send(withFiles)

            expect({ outcomes: [first.kind, second.kind], connections: ses.connections.size }).toEqual({
                outcomes: ['accepted', 'accepted'],
                connections: 2,
            })
        }
    )

    it('sends an email with files once, also when the caller passes a retry strategy', async () => {
        let requests = 0
        const port = await listen(
            createServer((request) => {
                request.resume()
                request.on('end', () => {
                    requests++
                    request.socket.destroy()
                })
            })
        )
        const options = {
            region: 'us-east-1',
            endpoint: `http://127.0.0.1:${port}`,
            credentials: { accessKeyId: 'fake-ses', secretAccessKey: 'fake-ses' },
            retryStrategy: retriesTwice,
        }
        transport = new SesTransport(options)

        const outcome = await transport.send(withFiles)

        expect({ outcome: outcome.kind, requests }).toEqual({ outcome: 'unknown', requests: 1 })
    })

    it.each([
        ['SES refuses the connection', (): string => ENDPOINT_THAT_REFUSES_CONNECTIONS, 'ECONNREFUSED'],
        [
            'every address of the SES host refuses the connection',
            (): string => {
                lookupAnswers('ses.example.test', loopbackAddresses('127.0.0.1', '127.0.0.2'))
                return 'http://ses.example.test:1'
            },
            'ECONNREFUSED 127.0.0.2:1',
        ],
        [
            'the SES host does not resolve',
            (): string => {
                lookupAnswers('ses.invalid', notFound)
                return 'http://ses.invalid'
            },
            'ENOTFOUND',
        ],
        [
            'the network to the SES host is unreachable',
            (): string => {
                lookupAnswers('ses.unreachable.test', networkUnreachable)
                return 'https://ses.unreachable.test'
            },
            'ENETUNREACH',
        ],
    ])(
        'when %s, counts a send with files as before_connect with the reason, because it never reached SES',
        async (_name, endpoint, reason) => {
            transport = sesTransportFor({ endpoint: endpoint() })
            const labels = { result: 'before_connect' }
            const before = await metricValue('cdp_ses_send_results_total', labels)

            const outcome = await transport.send(withFiles)

            expect({
                outcome: outcome.kind === 'not_sent' ? outcome.reason : outcome.kind,
                message: 'message' in outcome ? outcome.message : undefined,
                counted: (await metricValue('cdp_ses_send_results_total', labels)) - before,
            }).toEqual({ outcome: 'before_connect', message: expect.stringContaining(reason), counted: 1 })
        }
    )
})
