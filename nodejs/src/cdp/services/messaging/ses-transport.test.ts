import { LookupAnswer, lookupAnswers, loopbackAddresses } from '~/tests/helpers/mocks/dns.mock'

import { IncomingMessage, RequestListener, ServerResponse, createServer } from 'node:http'
import { createServer as createTlsServer } from 'node:https'
import { AddressInfo, Server, Socket } from 'node:net'
import tls from 'node:tls'
import { register } from 'prom-client'

import { ENDPOINT_THAT_REFUSES_CONNECTIONS, attachmentFile, sesTransportFor } from '~/cdp/_tests/email-delivery-fakes'

import { SesTransport } from './ses-transport'

const SDK_SOCKETS_PER_HOST = 50
const SENDS_QUEUED_FOR_A_SOCKET_GIVE_UP_MS = 10_000

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
            let heldAtOnce = 0
            const ses = await sesPeer(protocol, (_request, response) => {
                held.push(response)
                heldAtOnce = Math.max(heldAtOnce, held.length)
                if (held.length === inFlight) {
                    held.forEach((answer, index) => answerAccepted(answer, `m-${index}`))
                }
            })
            transport = sesTransportFor({ endpoint: ses.endpoint })
            const deadline = AbortSignal.timeout(SENDS_QUEUED_FOR_A_SOCKET_GIVE_UP_MS)

            const outcomes = await Promise.all(
                Array.from({ length: inFlight }, () => transport!.send({ email, files, deadline }))
            )

            expect({
                heldAtOnce,
                accepted: outcomes.filter(({ kind }) => kind === 'accepted').length,
                connections: ses.connections.size,
            }).toEqual({ heldAtOnce: inFlight, accepted: inFlight, connections: inFlight })
        },
        SENDS_QUEUED_FOR_A_SOCKET_GIVE_UP_MS * 2
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

    it.each([
        ['closes the connection', (socket: Socket): void => void socket.destroy()],
        ['resets the connection', (socket: Socket): void => void socket.resetAndDestroy()],
    ])(
        'when SES reads the request and %s, sends an email with files once and counts it as possibly sent, also when the caller passes a retry strategy',
        async (_name, endTheConnection) => {
            let requests = 0
            const port = await listen(
                createServer((request) => {
                    request.resume()
                    request.on('end', () => {
                        requests++
                        endTheConnection(request.socket)
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
        }
    )

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
        ['the kernel finds no route for the connection', (): string => 'https://255.255.255.255', 'ENETUNREACH'],
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
    const answerSesError = (response: ServerResponse, status: number, errorType: string): void => {
        response
            .writeHead(status, {
                'content-type': 'application/json',
                'x-amzn-errortype': errorType,
                connection: 'close',
            })
            .end(JSON.stringify({ message: errorType }))
    }

    const SES = ['127.0.0.1']
    const NOTHING_LISTENS = ['127.0.0.2', '127.0.0.3']
    const internalFailure = [500, 'InternalFailure'] as const
    const throttle = [429, 'TooManyRequestsException'] as const
    const throttledRetryOfAPossiblySentEmail = {
        kind: 'unknown',
        message:
            'SES throttled a retry after an earlier attempt that may have sent the email, so it is not sent again.',
    }

    it.each([
        [
            'answers 500, then throttles both retries',
            [SES],
            [internalFailure, throttle, throttle],
            throttledRetryOfAPossiblySentEmail,
            1,
        ],
        [
            'answers 500, every address refuses the next connection, then SES throttles the last retry',
            [SES, NOTHING_LISTENS, SES],
            [internalFailure, throttle],
            throttledRetryOfAPossiblySentEmail,
            1,
        ],
        [
            'every address refuses the first connection, then SES throttles both retries',
            [NOTHING_LISTENS, SES],
            [throttle, throttle],
            {
                kind: 'not_sent',
                reason: 'throttled',
                errorName: 'TooManyRequestsException',
                message: 'TooManyRequestsException',
            },
            0,
        ],
    ])(
        'when %s, an email without files ends as the attempts that may have reached SES say',
        async (_name, addressesForEachLookup, answers, expectedOutcome, countedAsMayHaveSent) => {
            const requests: number[] = []
            const port = await listen(
                createServer((request, response) => {
                    request.resume()
                    request.on('end', () => {
                        const [status, errorType] = answers[requests.length]
                        requests.push(status)
                        answerSesError(response, status, errorType)
                    })
                })
            )
            let lookups = 0
            lookupAnswers('ses.example.test', (options, callback) =>
                loopbackAddresses(...addressesForEachLookup[Math.min(lookups++, addressesForEachLookup.length - 1)])(
                    options,
                    callback
                )
            )
            const options = {
                region: 'us-east-1',
                endpoint: `http://ses.example.test:${port}`,
                credentials: { accessKeyId: 'fake-ses', secretAccessKey: 'fake-ses' },
                retryStrategy: retriesTwice,
            }
            transport = new SesTransport(options)
            const labels = { result: 'may_have_sent' }
            const before = await metricValue('cdp_ses_send_results_total', labels)

            const outcome = await transport.send({ email })

            expect({
                outcome,
                answered: requests,
                counted: (await metricValue('cdp_ses_send_results_total', labels)) - before,
            }).toEqual({
                outcome: expectedOutcome,
                answered: answers.map(([status]) => status),
                counted: countedAsMayHaveSent,
            })
        }
    )
})
