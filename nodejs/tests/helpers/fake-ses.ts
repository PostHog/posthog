import { IncomingMessage, Server, ServerResponse, createServer } from 'http'
import { AddressInfo } from 'net'

import { parseJSON } from '~/common/utils/json-parse'

const SEND_EMAIL_MEMBERS = new Set([
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

export type FakeSesConfigurationSet = { opens: boolean; clicks: boolean }

export type FakeSesDelivery = {
    to: string[]
    subject: string
    html: string
    configurationSetName: string
}

type NameValue = { Name: string; Value: string }

type SentMail = {
    timestamp: string
    source: string
    messageId: string
    destination: string[]
    headers: { name: string; value: string }[]
    commonHeaders: { subject: string }
    tags: Record<string, string[]>
}

export type FakeSesClickEvent = {
    eventType: 'Click'
    mail: SentMail
    click: { link: string; timestamp: string }
}

const ANCHOR = /<a\b[^>]*>/gi
const HREF = /\bhref\s*=\s*"(https?:\/\/[^"]*)"/i
const NO_TRACK = /\sses:no-track(?=[\s>=/])/i

export class FakeSes {
    readonly deliveries: FakeSesDelivery[] = []
    readonly clickEvents: FakeSesClickEvent[] = []
    opened = 0
    private links: { href: string; mail: SentMail }[] = []
    private origin = ''
    private server: Server | null = null

    constructor(private configurationSets: Record<string, FakeSesConfigurationSet>) {}

    async start(): Promise<string> {
        this.server = createServer((req, res) => void this.handle(req, res))
        await new Promise<void>((resolve) => this.server!.listen(0, '127.0.0.1', resolve))
        this.origin = `http://127.0.0.1:${(this.server.address() as AddressInfo).port}`
        return this.origin
    }

    async stop(): Promise<void> {
        await new Promise<void>((resolve) => (this.server ? this.server.close(() => resolve()) : resolve()))
    }

    private async handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
        const chunks: Buffer[] = []
        for await (const chunk of req) {
            chunks.push(chunk as Buffer)
        }
        const click = req.method === 'GET' && req.url?.match(/^\/L0\/(\d+)$/)
        const tracked = click && this.links[Number(click[1])]
        if (tracked) {
            this.clickEvents.push({
                eventType: 'Click',
                mail: tracked.mail,
                click: { link: tracked.href, timestamp: new Date().toISOString() },
            })
            res.writeHead(302, { Location: tracked.href })
            return void res.end()
        }
        if (req.method === 'GET' && req.url === '/I0/open.gif') {
            this.opened += 1
            res.writeHead(200, { 'Content-Type': 'image/gif' })
            return void res.end()
        }
        if (req.method !== 'POST' || req.url !== '/v2/email/outbound-emails') {
            return this.refuse(res, 404, 'NotFoundException', `No route for ${req.method} ${req.url}`)
        }
        const request = parseJSON(Buffer.concat(chunks).toString('utf-8'))
        const unknown = Object.keys(request).filter((member) => !SEND_EMAIL_MEMBERS.has(member))
        if (unknown.length) {
            return this.refuse(res, 400, 'BadRequestException', `Unknown members: ${unknown.join(', ')}`)
        }
        const configurationSet = this.configurationSets[request.ConfigurationSetName]
        if (request.ConfigurationSetName && !configurationSet) {
            return this.refuse(res, 404, 'NotFoundException', `Configuration set ${request.ConfigurationSetName}`)
        }
        const simple = request.Content?.Simple
        const messageId = `fake-ses-${this.deliveries.length + 1}`
        const subject = simple?.Subject?.Data ?? ''
        const mail: SentMail = {
            timestamp: new Date().toISOString(),
            source: request.FromEmailAddress ?? '',
            messageId,
            destination: request.Destination?.ToAddresses ?? [],
            headers: ((simple?.Headers ?? []) as NameValue[]).map(({ Name, Value }) => ({ name: Name, value: Value })),
            commonHeaders: { subject },
            tags: Object.fromEntries(
                ((request.EmailTags ?? []) as NameValue[]).map(({ Name, Value }) => [Name, [Value]])
            ),
        }
        this.deliveries.push({
            to: request.Destination?.ToAddresses ?? [],
            subject,
            html: this.track(simple?.Body?.Html?.Data ?? '', configurationSet, mail),
            configurationSetName: request.ConfigurationSetName ?? '',
        })
        res.writeHead(200, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ MessageId: messageId }))
    }

    private track(html: string, configurationSet: FakeSesConfigurationSet | undefined, mail: SentMail): string {
        let tracked = html
        if (configurationSet?.clicks) {
            tracked = tracked.replace(ANCHOR, (tag) =>
                NO_TRACK.test(tag)
                    ? tag
                    : tag.replace(
                          HREF,
                          (_m, href: string) => `href="${this.origin}/L0/${this.links.push({ href, mail }) - 1}"`
                      )
            )
        }
        if (configurationSet?.opens) {
            tracked = `${tracked}<img src="${this.origin}/I0/open.gif" />`
        }
        return tracked
    }

    private refuse(res: ServerResponse, status: number, type: string, message: string): void {
        res.writeHead(status, { 'Content-Type': 'application/json', 'x-amzn-ErrorType': type })
        res.end(JSON.stringify({ message }))
    }
}
