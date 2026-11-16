import { SESv2Client } from '@aws-sdk/client-sesv2'
import { createHash, randomBytes, randomUUID } from 'node:crypto'
import { IncomingMessage, Server, ServerResponse, createServer, request as httpRequest } from 'node:http'
import { AddressInfo } from 'node:net'

import { FakeSes, FakeSesAttachment } from '~/cdp/_tests/fake-ses'
import { getDefaultCdpConfig } from '~/cdp/config'
import { EmailAttachmentMetadata } from '~/cdp/schema/cyclotron'
import { AttachmentStore, buildAttachmentStore } from '~/cdp/services/messaging/attachment-store'

export const attachmentStoreConfig = {
    ...getDefaultCdpConfig(),
    CDP_EMAIL_ATTACHMENTS_S3_PREFIX: `email-attachments-test/${randomUUID()}`,
}
export const attachmentStore = buildAttachmentStore(attachmentStoreConfig)!

export type StoredFile = { bytes: Buffer; metadata: EmailAttachmentMetadata }

export const attachmentFile = (
    ref: Omit<Partial<EmailAttachmentMetadata>, 'sha256' | 'sizeBytes'> = {}
): StoredFile => {
    const bytes = Buffer.from(`%PDF-1.4 ${randomBytes(16).toString('hex')}`)
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
    ref: Omit<Partial<EmailAttachmentMetadata>, 'sha256' | 'sizeBytes'>
): Promise<StoredFile> => {
    const file = attachmentFile(ref)
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

export type BucketAnswer = 'pass' | 'refuse' | 'hold' | 'holdFilesItHas' | 'stallFileBodies'

export class BucketProxy {
    answer: BucketAnswer = 'pass'
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
        if (request.method === 'GET') {
            this.downloads++
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
        if (this.answer === 'hold') {
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
