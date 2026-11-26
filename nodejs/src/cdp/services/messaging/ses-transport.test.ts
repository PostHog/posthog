import dns from 'node:dns'
import { createServer } from 'node:http'
import { AddressInfo, Server, Socket, createServer as createTcpServer } from 'node:net'
import { register } from 'prom-client'

import { ENDPOINT_THAT_REFUSES_CONNECTIONS, attachmentFile, sesTransportFor } from '~/cdp/_tests/email-delivery-fakes'

import { SesTransport } from './ses-transport'

const SDK_SOCKETS_PER_HOST = 50

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
        if (jest.isMockFunction(dns.lookup)) {
            jest.mocked(dns.lookup).mockRestore()
        }
    })

    it.each(['http', 'https'])(
        'over %s, opens a connection for each email with files in flight, also past the sockets the SDK keeps per host',
        async (protocol) => {
            const inFlight = SDK_SOCKETS_PER_HOST + 1
            let connections = 0
            let allConnected: () => void = () => {}
            const connected = new Promise<void>((resolve) => (allConnected = resolve))
            const port = await listen(
                createTcpServer(() => {
                    connections++
                    if (connections === inFlight) {
                        allConnected()
                    }
                })
            )
            transport = sesTransportFor({ endpoint: `${protocol}://127.0.0.1:${port}` })
            const deadline = AbortSignal.timeout(5000)

            const sends = Promise.all(
                Array.from({ length: inFlight }, () => transport!.send({ email, files, deadline }))
            )
            await Promise.race([connected, new Promise((resolve) => deadline.addEventListener('abort', resolve))])
            peerSockets.forEach((socket) => socket.destroy())
            await sends

            expect(connections).toBe(inFlight)
        }
    )

    it('sends each email with files on a new connection, also after the last send closed', async () => {
        const connections = new Set<Socket>()
        let answered = 0
        const port = await listen(
            createServer((request, response) => {
                connections.add(request.socket)
                request.resume()
                request.on('end', () => {
                    answered++
                    response.writeHead(200, { 'content-type': 'application/json' }).end(`{"MessageId":"m-${answered}"}`)
                })
            })
        )
        transport = sesTransportFor({ endpoint: `http://127.0.0.1:${port}` })

        const first = await transport.send(withFiles)
        const second = await transport.send(withFiles)

        expect({ outcomes: [first.kind, second.kind], connections: connections.size }).toEqual({
            outcomes: ['accepted', 'accepted'],
            connections: 2,
        })
    })

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
