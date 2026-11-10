import { SESv2Client } from '@aws-sdk/client-sesv2'
import { createHash, randomBytes, randomUUID } from 'node:crypto'
import { IncomingMessage, Server, ServerResponse, createServer, request as httpRequest } from 'node:http'
import { AddressInfo } from 'node:net'

import { getDefaultCdpConfig } from '~/cdp/config'
import { EmailAttachmentMetadata } from '~/cdp/schema/cyclotron'
import { AttachmentStore, buildAttachmentStore } from '~/cdp/services/messaging/attachment-store'
import { parseJSON } from '~/common/utils/json-parse'

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

const readBody = async (request: IncomingMessage): Promise<Buffer> => {
    const chunks: Buffer[] = []
    for await (const chunk of request) {
        chunks.push(chunk as Buffer)
    }
    return Buffer.concat(chunks)
}

const listen = async (server: Server): Promise<string> => {
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    return `http://127.0.0.1:${(server.address() as AddressInfo).port}`
}

const shutDown = async (server: Server): Promise<void> => {
    server.closeAllConnections()
    await new Promise((resolve) => server.close(resolve))
}

export type DeliveredAttachment = {
    filename: string
    contentType: string | undefined
    contentId: string | undefined
    inline: boolean
    bytes: Buffer
}
export type DeliveredEmail = { to: string[]; attachments: DeliveredAttachment[] }

const SEND_EMAIL_FIELDS = new Set([
    'FromEmailAddress',
    'FromEmailAddressIdentityArn',
    'Destination',
    'ReplyToAddresses',
    'FeedbackForwardingEmailAddress',
    'FeedbackForwardingEmailAddressIdentityArn',
    'Content',
    'EmailTags',
    'ConfigurationSetName',
    'EndpointId',
    'TenantName',
    'ListManagementOptions',
])
const ATTACHMENT_FIELDS = new Set([
    'RawContent',
    'ContentDisposition',
    'FileName',
    'ContentDescription',
    'ContentId',
    'ContentTransferEncoding',
    'ContentType',
])

const deliveredBySes = (request: any): DeliveredEmail | string => {
    const unknown = Object.keys(request).find((field) => !SEND_EMAIL_FIELDS.has(field))
    if (unknown) {
        return `Unknown field ${unknown}`
    }
    const simple = request.Content?.Simple
    if (!request.FromEmailAddress || !request.Destination?.ToAddresses?.length || !simple?.Subject || !simple.Body) {
        return 'A sender, a recipient, a subject and a body are required'
    }
    const attachments: DeliveredAttachment[] = []
    for (const attachment of simple.Attachments ?? []) {
        const unknownInAttachment = Object.keys(attachment).find((field) => !ATTACHMENT_FIELDS.has(field))
        if (unknownInAttachment || !attachment.FileName || attachment.RawContent === undefined) {
            return 'An attachment needs a FileName and RawContent, and nothing else SES does not know'
        }
        if (!['ATTACHMENT', 'INLINE', undefined].includes(attachment.ContentDisposition)) {
            return `Unknown ContentDisposition ${attachment.ContentDisposition}`
        }
        attachments.push({
            filename: attachment.FileName,
            contentType: attachment.ContentType,
            contentId: attachment.ContentId,
            inline: attachment.ContentDisposition === 'INLINE',
            bytes: Buffer.from(attachment.RawContent, 'base64'),
        })
    }
    return { to: request.Destination.ToAddresses, attachments }
}

export type SesAnswer = 'accept' | 'reject' | 'throttle' | 'hold' | 'stallBody' | 'dropConnection'

// Speaks the SES v2 SendEmail wire protocol, so the real SDK client serializes, signs, retries and parses
// against it, and keeps what an accepted request would have delivered.
export class SesV2Fake {
    readonly delivered: DeliveredEmail[] = []
    answer: SesAnswer = 'accept'
    endpoint = ''
    private readonly server = createServer((request, response) => void this.handle(request, response))

    static async start(): Promise<SesV2Fake> {
        const fake = new SesV2Fake()
        fake.endpoint = await listen(fake.server)
        return fake
    }

    client(overrides: Partial<ConstructorParameters<typeof SESv2Client>[0]> = {}): SESv2Client {
        return sesClientWith({ endpoint: this.endpoint, ...overrides })
    }

    deliveredTo(address: string): DeliveredEmail[] {
        return this.delivered.filter((email) => email.to.some((to) => to.includes(address)))
    }

    close(): Promise<void> {
        return shutDown(this.server)
    }

    private async handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
        const body = await readBody(request)
        const error = (status: number, type: string, message: string): void => {
            response
                .writeHead(status, { 'content-type': 'application/json', 'x-amzn-errortype': type })
                .end(JSON.stringify({ message }))
        }
        if (request.method !== 'POST' || request.url !== '/v2/email/outbound-emails') {
            return error(404, 'NotFoundException', `No route for ${request.method} ${request.url}`)
        }
        switch (this.answer) {
            case 'hold':
                return
            case 'dropConnection':
                request.socket.destroy()
                return
            case 'stallBody':
                response.writeHead(200, { 'content-type': 'application/json' }).write('{"MessageId":')
                return
            case 'throttle':
                return error(429, 'TooManyRequestsException', 'Maximum sending rate exceeded.')
            case 'reject':
                return error(400, 'MessageRejected', 'Email address is not verified.')
        }
        const delivered = deliveredBySes(parseJSON(body.toString()))
        if (typeof delivered === 'string') {
            return error(400, 'BadRequestException', delivered)
        }
        this.delivered.push(delivered)
        response.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ MessageId: randomUUID() }))
    }
}

export type BucketAnswer = 'pass' | 'refuse' | 'hold' | 'holdFilesItHas' | 'stallFileBodies'

// Sits between the attachment store and the real bucket to fail or hold its requests on demand, which the
// shared bucket cannot do without disturbing everyone else using it.
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

    // Answers the requests it holds, and every one after, as `answer` says. A file whose body stalled is cut off.
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
                // The client gives up on a send's other downloads once one file is missing, which cuts a download
                // still waiting for its headers. Answering the missing file after another body stalled keeps that
                // download running.
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

export const sesClientWith = (overrides: Partial<ConstructorParameters<typeof SESv2Client>[0]>): SESv2Client =>
    new SESv2Client({
        region: 'us-east-1',
        credentials: { accessKeyId: 'AKIDEXAMPLE', secretAccessKey: 'example-secret' },
        ...overrides,
    })
