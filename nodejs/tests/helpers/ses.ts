import { SendEmailCommandInput } from '@aws-sdk/client-sesv2'
import { randomUUID } from 'node:crypto'
import { IncomingMessage, Server, ServerResponse, createServer } from 'node:http'
import { AddressInfo } from 'node:net'

import { parseJSON } from '~/common/utils/json-parse'

export type LocalSesEmail = {
    messageId: string
    from: string | undefined
    destination: { to: string[]; cc: string[]; bcc: string[] }
    replyTo: string[]
    subject: string | undefined
    body: { text?: string; html?: string }
    headers: { name: string | undefined; value: string | undefined }[]
}
export type LocalSesError = 'TooManyRequestsException' | 'LimitExceededException' | 'SendingPausedException'

export class LocalSes {
    readonly requests: SendEmailCommandInput[] = []
    private readonly deliveredEmails: LocalSesEmail[] = []
    private readonly server: Server
    private error: LocalSesError | undefined

    constructor() {
        this.server = createServer((request, response) => {
            void this.handleRequest(request, response).catch((error: Error) => {
                response.writeHead(500, { 'content-type': 'application/json' })
                response.end(JSON.stringify({ message: error.message }))
            })
        })
    }

    get endpoint(): string {
        return `http://127.0.0.1:${(this.server.address() as AddressInfo).port}`
    }

    async start(): Promise<void> {
        await new Promise<void>((resolve, reject) => {
            this.server.once('error', reject)
            this.server.listen(0, '127.0.0.1', () => {
                this.server.removeListener('error', reject)
                resolve()
            })
        })
    }

    async stop(): Promise<void> {
        await new Promise<void>((resolve, reject) => {
            this.server.close((error) => (error ? reject(error) : resolve()))
        })
    }

    setError(error: LocalSesError | undefined): void {
        this.error = error
    }

    getEmails(): Promise<LocalSesEmail[]> {
        return Promise.resolve([...this.deliveredEmails])
    }

    private async handleRequest(request: IncomingMessage, response: ServerResponse): Promise<void> {
        if (request.method !== 'POST' || request.url !== '/v2/email/outbound-emails') {
            response.writeHead(404)
            response.end()
            return
        }
        const input = parseJSON(await readBody(request)) as SendEmailCommandInput
        this.requests.push(input)

        if (this.error) {
            response.writeHead(this.error === 'TooManyRequestsException' ? 429 : 400, {
                'content-type': 'application/json',
                'x-amzn-errortype': this.error,
            })
            response.end(JSON.stringify({ message: `Local SES injected ${this.error}` }))
            return
        }

        const messageId = randomUUID()
        this.deliveredEmails.push(toEmail(messageId, input))
        response.writeHead(200, { 'content-type': 'application/json' })
        response.end(JSON.stringify({ MessageId: messageId }))
    }
}

async function readBody(request: IncomingMessage): Promise<string> {
    const chunks: Buffer[] = []
    for await (const chunk of request) {
        chunks.push(Buffer.from(chunk))
    }
    return Buffer.concat(chunks).toString('utf8')
}

function toEmail(messageId: string, input: SendEmailCommandInput): LocalSesEmail {
    const simple = input.Content?.Simple
    return {
        messageId,
        from: input.FromEmailAddress,
        destination: {
            to: input.Destination?.ToAddresses ?? [],
            cc: input.Destination?.CcAddresses ?? [],
            bcc: input.Destination?.BccAddresses ?? [],
        },
        replyTo: input.ReplyToAddresses ?? [],
        subject: simple?.Subject?.Data,
        body: { text: simple?.Body?.Text?.Data, html: simple?.Body?.Html?.Data },
        headers: (simple?.Headers ?? []).map(({ Name, Value }) => ({ name: Name, value: Value })),
    }
}
