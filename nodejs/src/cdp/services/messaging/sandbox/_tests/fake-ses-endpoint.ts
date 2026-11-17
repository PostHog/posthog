import { IncomingMessage, Server, ServerResponse, createServer } from 'http'
import { AddressInfo, Socket } from 'net'
import addressparser from 'nodemailer/lib/addressparser'

import { parseJSON } from '~/common/utils/json-parse'

export type Mailbox = { name: string; address: string }

export type DeliveredEmail = {
    messageId: string
    from: Mailbox
    to: Mailbox[]
    cc: string[]
    bcc: string[]
    replyTo: string[]
    subject: string
    text?: string
    html?: string
    headers: Record<string, string>
    tags: Record<string, string>
    tenantName?: string
    configurationSet?: string
}

export type SesReply =
    | { kind: 'error'; status: number; errorType: string }
    | { kind: 'accept-without-id' }
    | { kind: 'hang' }
    | { kind: 'deliver-without-reply' }
    | { kind: 'deliver-then-reset' }
    | { kind: 'drop' }

export const SES_THROTTLE: SesReply = { kind: 'error', status: 400, errorType: 'ThrottlingException' }
export const SES_SENDING_RATE: SesReply = { kind: 'error', status: 429, errorType: 'TooManyRequestsException' }
export const SES_SERVER_ERROR: SesReply = { kind: 'error', status: 500, errorType: 'InternalFailure' }
export const SES_REJECTED: SesReply = { kind: 'error', status: 400, errorType: 'MessageRejected' }

const SEND_EMAIL_PATH = '/v2/email/outbound-emails'

export class FakeSesEndpoint {
    readonly delivered: DeliveredEmail[] = []
    attempts = 0
    private replies: SesReply[] = []
    private everyReply: SesReply | null = null
    private server: Server | null = null
    private readonly sockets = new Set<Socket>()
    private savedCredentials: Record<string, string | undefined> = {}

    replyNext(...replies: SesReply[]): void {
        this.replies.push(...replies)
    }

    replyAlways(reply: SesReply | null): void {
        this.everyReply = reply
    }

    async start(): Promise<string> {
        this.savedCredentials = {
            AWS_ACCESS_KEY_ID: process.env.AWS_ACCESS_KEY_ID,
            AWS_SECRET_ACCESS_KEY: process.env.AWS_SECRET_ACCESS_KEY,
        }
        process.env.AWS_ACCESS_KEY_ID = 'fake-ses-access-key'
        process.env.AWS_SECRET_ACCESS_KEY = 'fake-ses-secret-key'
        this.server = createServer((req, res) => void this.handle(req, res))
        this.server.on('connection', (socket) => {
            this.sockets.add(socket)
            socket.on('close', () => this.sockets.delete(socket))
        })
        await new Promise<void>((resolve) => this.server!.listen(0, '127.0.0.1', resolve))
        return `http://127.0.0.1:${(this.server.address() as AddressInfo).port}`
    }

    dropConnections(): void {
        for (const socket of this.sockets) {
            socket.destroy()
        }
    }

    async stop(): Promise<void> {
        this.dropConnections()
        await new Promise<void>((resolve) => (this.server ? this.server.close(() => resolve()) : resolve()))
        for (const [key, value] of Object.entries(this.savedCredentials)) {
            if (value === undefined) {
                delete process.env[key]
            } else {
                process.env[key] = value
            }
        }
    }

    private async handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
        const body = await readBody(req)
        if (req.method !== 'POST' || req.url !== SEND_EMAIL_PATH) {
            respond(res, 404, { message: `No such operation: ${req.method} ${req.url}` }, 'UnknownOperationException')
            return
        }
        this.attempts += 1
        const reply = this.replies.shift() ?? this.everyReply
        if (reply?.kind === 'hang') {
            return
        }
        if (reply?.kind === 'deliver-without-reply') {
            this.delivered.push(toDeliveredEmail(parseJSON(body), `ses-${this.delivered.length + 1}`))
            return
        }
        if (reply?.kind === 'deliver-then-reset') {
            this.delivered.push(toDeliveredEmail(parseJSON(body), `ses-${this.delivered.length + 1}`))
            req.socket.resetAndDestroy()
            return
        }
        if (reply?.kind === 'drop') {
            req.socket.destroy()
            return
        }
        if (reply?.kind === 'error') {
            respond(res, reply.status, { message: reply.errorType }, reply.errorType)
            return
        }
        if (reply?.kind === 'accept-without-id') {
            respond(res, 200, {})
            return
        }
        const email = toDeliveredEmail(parseJSON(body), `ses-${this.delivered.length + 1}`)
        this.delivered.push(email)
        respond(res, 200, { MessageId: email.messageId })
    }
}

function readBody(req: IncomingMessage): Promise<string> {
    return new Promise((resolve, reject) => {
        const chunks: Buffer[] = []
        req.on('data', (chunk: Buffer) => chunks.push(chunk))
        req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
        req.on('error', reject)
    })
}

function respond(res: ServerResponse, status: number, body: object, errorType?: string): void {
    res.writeHead(status, {
        'Content-Type': 'application/json',
        'x-amzn-RequestId': 'fake-request-id',
        ...(errorType ? { 'x-amzn-ErrorType': errorType } : {}),
    })
    res.end(JSON.stringify(body))
}

type SendEmailInput = {
    FromEmailAddress: string
    Destination?: { ToAddresses?: string[]; CcAddresses?: string[]; BccAddresses?: string[] }
    ReplyToAddresses?: string[]
    ConfigurationSetName?: string
    TenantName?: string
    EmailTags?: { Name: string; Value: string }[]
    Content: {
        Simple: {
            Subject: { Data: string }
            Body: { Text?: { Data: string }; Html?: { Data: string } }
            Headers?: { Name: string; Value: string }[]
        }
    }
}

function toDeliveredEmail(input: SendEmailInput, messageId: string): DeliveredEmail {
    const simple = input.Content.Simple
    return {
        messageId,
        from: parseMailboxes(input.FromEmailAddress)[0],
        to: (input.Destination?.ToAddresses ?? []).flatMap(parseMailboxes),
        cc: input.Destination?.CcAddresses ?? [],
        bcc: input.Destination?.BccAddresses ?? [],
        replyTo: input.ReplyToAddresses ?? [],
        subject: simple.Subject.Data,
        text: simple.Body.Text?.Data,
        html: simple.Body.Html?.Data,
        headers: Object.fromEntries((simple.Headers ?? []).map(({ Name, Value }) => [Name, Value])),
        tags: Object.fromEntries((input.EmailTags ?? []).map(({ Name, Value }) => [Name, Value])),
        tenantName: input.TenantName,
        configurationSet: input.ConfigurationSetName,
    }
}

function parseMailboxes(field: string): Mailbox[] {
    return addressparser(field, { flatten: true }).map(({ name, address }) => ({
        name: decodeMimeWords(name),
        address,
    }))
}

function decodeMimeWords(value: string): string {
    return value.replace(/=\?([^?]+)\?([BbQq])\?([^?]*)\?=/g, (_word, _charset, encoding: string, text: string) =>
        encoding.toUpperCase() === 'B'
            ? Buffer.from(text, 'base64').toString('utf8')
            : Buffer.from(
                  text
                      .replace(/_/g, ' ')
                      .replace(/=([0-9A-Fa-f]{2})/g, (_hex, code: string) => String.fromCharCode(parseInt(code, 16))),
                  'latin1'
              ).toString('utf8')
    )
}
