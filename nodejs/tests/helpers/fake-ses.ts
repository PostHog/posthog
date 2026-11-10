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

export const FAKE_SES_CLICK_PREFIX = 'https://r.fake-ses.example/L0/'
export const FAKE_SES_OPEN_PIXEL = 'https://r.fake-ses.example/I0/open.gif'

export type FakeSesConfigurationSet = { opens: boolean; clicks: boolean }

export type FakeSesDelivery = {
    to: string[]
    subject: string
    html: string
    configurationSetName: string
}

const ANCHOR = /<a\b[^>]*>/gi
const HREF = /\bhref\s*=\s*"(https?:\/\/[^"]*)"/i
const NO_TRACK = /\sses:no-track(?=[\s>=/])/i

export class FakeSes {
    readonly deliveries: FakeSesDelivery[] = []
    private server: Server | null = null

    constructor(private configurationSets: Record<string, FakeSesConfigurationSet>) {}

    async start(): Promise<string> {
        this.server = createServer((req, res) => void this.handle(req, res))
        await new Promise<void>((resolve) => this.server!.listen(0, '127.0.0.1', resolve))
        return `http://127.0.0.1:${(this.server.address() as AddressInfo).port}`
    }

    async stop(): Promise<void> {
        await new Promise<void>((resolve) => (this.server ? this.server.close(() => resolve()) : resolve()))
    }

    private async handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
        const chunks: Buffer[] = []
        for await (const chunk of req) {
            chunks.push(chunk as Buffer)
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
        this.deliveries.push({
            to: request.Destination?.ToAddresses ?? [],
            subject: simple?.Subject?.Data ?? '',
            html: this.track(simple?.Body?.Html?.Data ?? '', configurationSet),
            configurationSetName: request.ConfigurationSetName ?? '',
        })
        res.writeHead(200, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ MessageId: `fake-ses-${this.deliveries.length}` }))
    }

    private track(html: string, configurationSet: FakeSesConfigurationSet | undefined): string {
        let tracked = html
        if (configurationSet?.clicks) {
            tracked = tracked.replace(ANCHOR, (tag) =>
                NO_TRACK.test(tag)
                    ? tag
                    : tag.replace(
                          HREF,
                          (_m, href: string) => `href="${FAKE_SES_CLICK_PREFIX}${encodeURIComponent(href)}"`
                      )
            )
        }
        if (configurationSet?.opens) {
            tracked = `${tracked}<img src="${FAKE_SES_OPEN_PIXEL}" />`
        }
        return tracked
    }

    private refuse(res: ServerResponse, status: number, type: string, message: string): void {
        res.writeHead(status, { 'Content-Type': 'application/json', 'x-amzn-ErrorType': type })
        res.end(JSON.stringify({ message }))
    }
}
