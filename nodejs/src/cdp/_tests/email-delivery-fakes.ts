import { SESv2Client } from '@aws-sdk/client-sesv2'
import { createHash, randomBytes, randomUUID } from 'node:crypto'
import { IncomingMessage, Server, ServerResponse, createServer, request as httpRequest } from 'node:http'
import { AddressInfo, Socket, connect, createServer as createTcpServer } from 'node:net'

import { FakeSes, FakeSesAttachment } from '~/cdp/_tests/fake-ses'
import { getDefaultCdpConfig } from '~/cdp/config'
import { EmailAttachmentMetadata } from '~/cdp/schema/cyclotron'
import { CyclotronJobQueuePostgresV2 } from '~/cdp/services/job-queue/job-queue-postgres-v2'
import { AttachmentStore, buildAttachmentStore } from '~/cdp/services/messaging/attachment-store'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '~/cdp/types'

export const attachmentStoreConfig = {
    ...getDefaultCdpConfig(),
    CDP_EMAIL_ATTACHMENTS_S3_PREFIX: `email-attachments-test/${randomUUID()}`,
}
export const attachmentStore = buildAttachmentStore(attachmentStoreConfig)!

export type StoredFile = { bytes: Buffer; metadata: EmailAttachmentMetadata }

export const attachmentFile = (
    ref: Omit<Partial<EmailAttachmentMetadata>, 'sha256' | 'sizeBytes'> = {},
    bytes: Buffer = Buffer.from(`%PDF-1.4 ${randomBytes(16).toString('hex')}`)
): StoredFile => {
    return {
        bytes,
        metadata: {
            filename: 'a.pdf',
            ...ref,
            sha256: createHash('sha256').update(bytes).digest('hex'),
            sizeBytes: bytes.length,
        },
    }
}

export const uploadAttachment = async (
    teamId: number,
    ref: Omit<Partial<EmailAttachmentMetadata>, 'sha256' | 'sizeBytes'>,
    bytes?: Buffer
): Promise<StoredFile> => {
    const file = attachmentFile(ref, bytes)
    const [slot] = await attachmentStore.prepareUploads(teamId, [
        { sha256: file.metadata.sha256, size: file.bytes.length },
    ])
    if (slot.status !== 'upload') {
        throw new Error(`expected an upload slot, got ${slot.status}`)
    }
    const { internalFetch } = jest.requireActual('~/common/utils/request')
    const response = await internalFetch(slot.url, { method: slot.method, headers: slot.headers, body: file.bytes })
    expect(response.status).toBe(200)
    return file
}

const listen = async (server: Server): Promise<string> => {
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    return `http://127.0.0.1:${(server.address() as AddressInfo).port}`
}

const shutDown = async (server: Server): Promise<void> => {
    server.closeAllConnections()
    await new Promise((resolve) => server.close(resolve))
}

export type DeliveredEmail = { to: string[]; attachments: FakeSesAttachment[] }

export const deliveredTo = (ses: FakeSes, address: string): DeliveredEmail[] =>
    ses.sent
        .filter((message) => message.to.some((to) => to.includes(address)))
        .map(({ to, attachments }) => ({ to, attachments }))

export type BucketAnswer = 'pass' | 'refuse' | 'hold' | 'holdCopies' | 'holdFilesItHas' | 'stallFileBodies'

export class BucketProxy {
    answer: BucketAnswer = 'pass'
    lastModifiedAgeMs = 0
    requests = 0
    copies = 0
    abandonedRequests = 0
    downloads = 0
    endpoint = ''
    private held: (() => void)[] = []
    private stalled: ServerResponse[] = []
    private bodyStalled: () => void = () => undefined
    private readonly aBodyStalled = new Promise<void>((resolve) => (this.bodyStalled = resolve))
    private readonly server = createServer((request, response) => this.handle(request, response))

    static async start(): Promise<BucketProxy> {
        const proxy = new BucketProxy()
        proxy.endpoint = await listen(proxy.server)
        return proxy
    }

    get heldRequests(): number {
        return this.held.length + this.stalled.length
    }

    store(): AttachmentStore {
        return buildAttachmentStore({ ...attachmentStoreConfig, CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT: this.endpoint })!
    }

    release(answer: 'pass' | 'refuse' = 'pass'): void {
        this.answer = answer
        for (const answerHeld of this.held.splice(0)) {
            answerHeld()
        }
        for (const response of this.stalled.splice(0)) {
            response.destroy()
        }
    }

    close(): Promise<void> {
        return shutDown(this.server)
    }

    private handle(request: IncomingMessage, response: ServerResponse): void {
        response.on('close', () => {
            if (!response.writableEnded) {
                this.abandonedRequests++
            }
        })
        this.requests++
        if (request.method === 'GET') {
            this.downloads++
        }
        if (request.headers['x-amz-copy-source']) {
            this.copies++
        }
        this.answerRequest(request, response)
    }

    private answerRequest(request: IncomingMessage, response: ServerResponse): void {
        if (response.destroyed) {
            return
        }
        if (this.answer === 'refuse') {
            request.socket.destroy()
            return
        }
        if (this.answer === 'hold' || (this.answer === 'holdCopies' && request.headers['x-amz-copy-source'])) {
            this.held.push(() => this.answerRequest(request, response))
            return
        }
        const upstream = httpRequest(
            `${attachmentStoreConfig.CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT}${request.url}`,
            { method: request.method, headers: request.headers },
            (answer) => {
                const fileItHas = request.method === 'GET' && answer.statusCode === 200
                if (request.method === 'GET' && !fileItHas && this.answer === 'stallFileBodies') {
                    void this.aBodyStalled.then(() => {
                        response.writeHead(answer.statusCode!, answer.headers)
                        answer.pipe(response)
                    })
                    return
                }
                if (fileItHas && this.answer === 'holdFilesItHas') {
                    answer.resume()
                    return
                }
                if (request.method === 'HEAD' && this.lastModifiedAgeMs && answer.headers['last-modified']) {
                    answer.headers['last-modified'] = new Date(
                        Date.parse(answer.headers['last-modified']) - this.lastModifiedAgeMs
                    ).toUTCString()
                }
                response.writeHead(answer.statusCode!, answer.headers)
                if (fileItHas && this.answer === 'stallFileBodies') {
                    answer.once('data', (chunk: Buffer) => {
                        response.write(chunk.subarray(0, 1))
                        setTimeout(this.bodyStalled, 100)
                    })
                    answer.resume()
                    this.stalled.push(response)
                    return
                }
                answer.pipe(response)
            }
        )
        request.pipe(upstream)
    }
}

export const sesClientFor = (
    ses: FakeSes,
    overrides: Partial<ConstructorParameters<typeof SESv2Client>[0]> = {}
): SESv2Client =>
    new SESv2Client({
        region: 'us-east-1',
        endpoint: ses.endpoint,
        credentials: { accessKeyId: 'fake-ses', secretAccessKey: 'fake-ses' },
        ...overrides,
    })

export class EmailQueueOfOneTest extends CyclotronJobQueuePostgresV2 {
    constructor(
        private readonly queueName: string,
        config: ConstructorParameters<typeof CyclotronJobQueuePostgresV2>[1]
    ) {
        super(10, config)
    }

    public override startAsConsumer(
        _queue: CyclotronJobQueueKind,
        consumeBatch: (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>
    ): Promise<void> {
        return super.startAsConsumer(this.queueName as CyclotronJobQueueKind, (invocations) =>
            consumeBatch(invocations.map((invocation) => ({ ...invocation, queue: 'email' })))
        )
    }

    public override queueInvocations(invocations: CyclotronJobInvocation[]): Promise<void> {
        return super.queueInvocations(invocations.map((invocation) => this.onOwnQueue(invocation)))
    }

    public override queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        return super.queueInvocationResults(
            results.map((result) => ({ ...result, invocation: this.onOwnQueue(result.invocation) }))
        )
    }

    private onOwnQueue(invocation: CyclotronJobInvocation): CyclotronJobInvocation {
        const queue = invocation.queue === 'email' ? this.queueName : `${this.queueName}/${invocation.queue}`
        return { ...invocation, queue: queue as CyclotronJobQueueKind }
    }
}

export type HeldQuery = { release: () => void; drop: () => void }

const SSL_REQUEST = 80877103
const GSS_ENCRYPTION_REQUEST = 80877104
const ENDS_A_REQUEST = new Set(['S', 'Q', 'X', 'p', 'H', 'c', 'f'])

export class PostgresProxy {
    url = ''
    private readonly waiting: { matches: (request: string) => boolean; caught: (held: HeldQuery) => void }[] = []
    private readonly holding = new Set<HeldQuery>()
    private readonly sockets = new Set<Socket>()
    private readonly server = createTcpServer((client) => this.forward(client))

    static async start(upstream: URL): Promise<PostgresProxy> {
        const proxy = new PostgresProxy(upstream)
        await new Promise<void>((resolve) => proxy.server.listen(0, '127.0.0.1', resolve))
        const url = new URL(upstream)
        url.host = `127.0.0.1:${(proxy.server.address() as AddressInfo).port}`
        proxy.url = url.toString()
        return proxy
    }

    private constructor(private readonly upstream: URL) {}

    hold(matches: (request: string) => boolean): Promise<HeldQuery> {
        return new Promise((caught) => this.waiting.push({ matches, caught }))
    }

    releaseAll(): void {
        this.waiting.splice(0)
        for (const held of this.holding) {
            held.release()
        }
    }

    async close(): Promise<void> {
        for (const socket of this.sockets) {
            socket.destroy()
        }
        await new Promise((resolve) => this.server.close(resolve))
    }

    private forward(client: Socket): void {
        const upstream = connect(Number(this.upstream.port || 5432), this.upstream.hostname)
        for (const socket of [client, upstream]) {
            this.sockets.add(socket)
            socket.on('error', () => undefined)
            socket.on('close', () => {
                client.destroy()
                upstream.destroy()
            })
        }
        upstream.pipe(client)

        let unread = Buffer.alloc(0)
        let request: Buffer[] = []
        let startedUp = false
        let paused = false
        const forwardRequests = (): void => {
            while (!paused) {
                const typeBytes = startedUp ? 1 : 0
                if (unread.length < typeBytes + 4) {
                    return
                }
                const length = typeBytes + unread.readInt32BE(typeBytes)
                if (unread.length < length) {
                    return
                }
                const message = unread.subarray(0, length)
                unread = unread.subarray(length)
                if (!startedUp) {
                    const code = message.readInt32BE(4)
                    startedUp = code !== SSL_REQUEST && code !== GSS_ENCRYPTION_REQUEST
                    upstream.write(message)
                    continue
                }
                request.push(message)
                if (!ENDS_A_REQUEST.has(String.fromCharCode(message[0]))) {
                    continue
                }
                const whole = Buffer.concat(request)
                request = []
                const index = this.waiting.findIndex(({ matches }) => matches(whole.toString('latin1')))
                if (index === -1) {
                    upstream.write(whole)
                    continue
                }
                const [{ caught }] = this.waiting.splice(index, 1)
                paused = true
                const held: HeldQuery = {
                    release: () => {
                        this.holding.delete(held)
                        upstream.write(whole)
                        paused = false
                        forwardRequests()
                    },
                    drop: () => {
                        this.holding.delete(held)
                        client.destroy()
                    },
                }
                this.holding.add(held)
                caught(held)
            }
        }
        client.on('data', (chunk: Buffer) => {
            unread = Buffer.concat([unread, chunk])
            forwardRequests()
        })
    }
}
