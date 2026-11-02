import { SendEmailCommandInput } from '@aws-sdk/client-sesv2'
import { IncomingMessage, Server, ServerResponse, createServer } from 'node:http'
import { AddressInfo } from 'node:net'
import { isNativeError } from 'node:util/types'
import { z } from 'zod'

import { parseJSON } from '~/common/utils/json-parse'

const fetchLocalSes = globalThis.fetch

const storedEmailSchema = z.object({
    messageId: z.string().min(1),
    from: z.string(),
    destination: z.object({ to: z.array(z.string()), cc: z.array(z.string()), bcc: z.array(z.string()) }),
    replyTo: z.array(z.string()),
    subject: z.string(),
    body: z.object({ text: z.string().optional(), html: z.string().optional() }),
    headers: z.array(z.object({ name: z.string(), value: z.string() })),
})

export type LocalSesEmail = z.infer<typeof storedEmailSchema>
export type LocalSesError = 'TooManyRequestsException' | 'LimitExceededException' | 'SendingPausedException'

export class LocalSes {
    readonly requests: SendEmailCommandInput[] = []
    private readonly messageIds = new Set<string>()
    private readonly server: Server
    private error: LocalSesError | undefined
    private errorsRemaining = Infinity

    constructor(private readonly fakeEndpoint = 'http://127.0.0.1:4566') {
        this.server = createServer((request, response) => {
            void this.handleRequest(request, response).catch((error: Error) => {
                response.writeHead(502, { 'content-type': 'application/json' })
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
        this.errorsRemaining = Infinity
    }

    throttleNextRequests(count: number): void {
        this.error = 'TooManyRequestsException'
        this.errorsRemaining = count
    }

    private async fetchFake(path: string, options: RequestInit = {}): Promise<Response> {
        try {
            return await fetchLocalSes(`${this.fakeEndpoint}${path}`, {
                ...options,
                signal: AbortSignal.timeout(10_000),
            })
        } catch (error) {
            const cause = isNativeError(error) && isNativeError(error.cause) ? error.cause.message : String(error)
            throw new Error(`Local SES fake unreachable at ${this.fakeEndpoint}: ${cause}`)
        }
    }

    async getEmails(): Promise<LocalSesEmail[]> {
        const response = await this.fetchFake('/store')
        if (!response.ok) {
            throw new Error(`Local SES inbox returned HTTP ${response.status}`)
        }
        const store = z
            .object({ emails: z.array(z.object({ messageId: z.string().min(1) }).passthrough()) })
            .safeParse(await response.json())
        if (!store.success) {
            throw new Error(`Local SES /store contract changed: ${store.error.message}`)
        }
        const emails = z
            .array(storedEmailSchema)
            .safeParse(store.data.emails.filter((email) => this.messageIds.has(email.messageId)))
        if (!emails.success) {
            throw new Error(`Local SES /store contract changed: ${emails.error.message}`)
        }
        return emails.data
    }

    private async handleRequest(request: IncomingMessage, response: ServerResponse): Promise<void> {
        if (request.method !== 'POST' || request.url !== '/v2/email/outbound-emails') {
            response.writeHead(404)
            response.end()
            return
        }
        const chunks: Buffer[] = []
        for await (const chunk of request) {
            chunks.push(Buffer.from(chunk))
        }
        const body = Buffer.concat(chunks).toString('utf8')
        this.requests.push(parseJSON(body) as SendEmailCommandInput)

        if (this.error && this.errorsRemaining > 0) {
            this.errorsRemaining--
            response.writeHead(this.error === 'TooManyRequestsException' ? 429 : 400, {
                'content-type': 'application/json',
                'x-amzn-errortype': this.error,
            })
            response.end(JSON.stringify({ message: `Local SES injected ${this.error}` }))
            return
        }

        const headers: Record<string, string> = {}
        for (const [name, value] of Object.entries(request.headers)) {
            if (typeof value === 'string' && name !== 'host' && name !== 'connection') {
                headers[name] = value
            }
        }
        const upstream = await this.fetchFake('/v2/email/outbound-emails', {
            method: 'POST',
            headers,
            body,
        })
        const responseBody = await upstream.text()
        if (upstream.ok) {
            const result = z.object({ MessageId: z.string().min(1) }).safeParse(parseJSON(responseBody))
            if (!result.success) {
                throw new Error(`Local SES SendEmail contract changed: ${result.error.message}`)
            }
            this.messageIds.add(result.data.MessageId)
        }
        response.writeHead(upstream.status, { 'content-type': 'application/json' })
        response.end(responseBody)
    }
}
