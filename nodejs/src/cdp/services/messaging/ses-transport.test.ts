import dns from 'node:dns'
import { IncomingMessage, RequestListener, ServerResponse, createServer } from 'node:http'
import { createServer as createTlsServer } from 'node:https'
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

type LookupAnswer = (options: dns.LookupOptions, callback: (...args: unknown[]) => void) => void

const lookupAnswers = (answeredHost: string, answer: LookupAnswer): void => {
    const lookup = dns.lookup as (...args: unknown[]) => void
    jest.spyOn(dns, 'lookup').mockImplementation(((host: string, ...rest: unknown[]) => {
        if (host !== answeredHost) {
            return lookup(host, ...rest)
        }
        const callback = rest[rest.length - 1] as (...args: unknown[]) => void
        const options = (typeof rest[0] === 'object' ? rest[0] : {}) as dns.LookupOptions
        process.nextTick(() => answer(options, callback))
    }) as typeof dns.lookup)
}

const notFound: LookupAnswer = (_options, callback) =>
    callback(
        Object.assign(new Error('getaddrinfo ENOTFOUND ses.invalid'), {
            code: 'ENOTFOUND',
            syscall: 'getaddrinfo',
            hostname: 'ses.invalid',
        })
    )

const twoLoopbackAddresses: LookupAnswer = (options, callback) =>
    options.all
        ? callback(null, [
              { address: '127.0.0.1', family: 4 },
              { address: '127.0.0.2', family: 4 },
          ])
        : callback(null, '127.0.0.1', 4)

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
            const ses = await sesPeer(protocol, (_request, response) => {
                held.push(response)
                if (held.length === inFlight) {
                    held.forEach((answer, index) => answerAccepted(answer, `m-${index}`))
                }
            })
            transport = sesTransportFor({ endpoint: ses.endpoint })
            const onlyIfAConnectionNeverOpens = AbortSignal.timeout(30000)

            const outcomes = await Promise.all(
                Array.from({ length: inFlight }, () =>
                    transport!.send({ email, files, deadline: onlyIfAConnectionNeverOpens })
                )
            )

            expect({
                accepted: outcomes.filter(({ kind }) => kind === 'accepted').length,
                connections: ses.connections.size,
            }).toEqual({ accepted: inFlight, connections: inFlight })
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
        ['SES refuses the connection', (): string => ENDPOINT_THAT_REFUSES_CONNECTIONS],
        [
            'every address of the SES host refuses the connection',
            (): string => {
                lookupAnswers('ses.example.test', twoLoopbackAddresses)
                return 'http://ses.example.test:1'
            },
        ],
        [
            'the SES host does not resolve',
            (): string => {
                lookupAnswers('ses.invalid', notFound)
                return 'http://ses.invalid'
            },
        ],
    ])('when %s, counts a send with files as before_connect, because it never reached SES', async (_name, endpoint) => {
        transport = sesTransportFor({ endpoint: endpoint() })
        const labels = { result: 'before_connect' }
        const before = await metricValue('cdp_ses_send_results_total', labels)

        const outcome = await transport.send(withFiles)

        expect({
            outcome: outcome.kind === 'not_sent' ? outcome.reason : outcome.kind,
            counted: (await metricValue('cdp_ses_send_results_total', labels)) - before,
        }).toEqual({ outcome: 'before_connect', counted: 1 })
    })
})
