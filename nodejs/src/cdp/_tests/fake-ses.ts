import http from 'http'
import { AddressInfo } from 'net'

import { parseJSON } from '~/common/utils/json-parse'

export interface FakeSesAttachment {
    filename: string
    contentType: string | undefined
    contentId: string | undefined
    inline: boolean
    bytes: Buffer
}

export interface FakeSesMessage {
    messageId: string
    from: string
    feedbackForwardingAddress: string | undefined
    to: string[]
    cc: string[] | undefined
    bcc: string[] | undefined
    replyTo: string[] | undefined
    subject: string
    text: string | undefined
    html: string | undefined
    charsets: { subject?: string; text?: string; html?: string }
    headers: Record<string, string>
    tags: Record<string, string>
    tenant: string | undefined
    configurationSet: string | undefined
    tracked: boolean
    attachments: FakeSesAttachment[]
}

export type FakeSesFault =
    | { status: number; type: string; message: string }
    | 'drop-connection'
    | 'no-answer'
    | 'stalled-body'

export interface FakeSes {
    endpoint: string
    sent: FakeSesMessage[]
    failWith(fault: FakeSesFault | null): void
    close(): Promise<void>
}

type ConfigurationSets = Record<string, { tracking: boolean }>

const SEND_EMAIL_PATH = '/v2/email/outbound-emails'

function respond(res: http.ServerResponse, status: number, body: object, errorType?: string): void {
    res.writeHead(status, {
        'content-type': 'application/json',
        ...(errorType ? { 'x-amzn-errortype': errorType } : {}),
    })
    res.end(JSON.stringify(body))
}

type NameValueList = { Name: string; Value: string }[]

function isNameValueList(entries: unknown): entries is NameValueList | undefined {
    return (
        entries === undefined ||
        (Array.isArray(entries) &&
            entries.every((entry) => typeof entry?.Name === 'string' && typeof entry?.Value === 'string'))
    )
}

const ATTACHMENT_FIELDS = new Set([
    'RawContent',
    'ContentDisposition',
    'FileName',
    'ContentDescription',
    'ContentId',
    'ContentTransferEncoding',
    'ContentType',
])

function toAttachments(entries: unknown): FakeSesAttachment[] | string {
    if (entries === undefined) {
        return []
    }
    if (!Array.isArray(entries)) {
        return 'Attachments must be a list.'
    }
    const attachments: FakeSesAttachment[] = []
    for (const entry of entries) {
        const unknownField = Object.keys(entry ?? {}).find((field) => !ATTACHMENT_FIELDS.has(field))
        if (unknownField) {
            return `Unknown attachment field ${unknownField}.`
        }
        if (typeof entry.FileName !== 'string' || typeof entry.RawContent !== 'string') {
            return 'Every attachment needs a FileName and RawContent.'
        }
        if (!['ATTACHMENT', 'INLINE', undefined].includes(entry.ContentDisposition)) {
            return `Unknown ContentDisposition ${entry.ContentDisposition}.`
        }
        attachments.push({
            filename: entry.FileName,
            contentType: entry.ContentType,
            contentId: entry.ContentId,
            inline: entry.ContentDisposition === 'INLINE',
            bytes: Buffer.from(entry.RawContent, 'base64'),
        })
    }
    return attachments
}

function toRecord(entries: NameValueList | undefined): Record<string, string> {
    return Object.fromEntries((entries ?? []).map(({ Name, Value }) => [Name, Value]))
}

export async function startFakeSes(configurationSets: ConfigurationSets): Promise<FakeSes> {
    const sent: FakeSesMessage[] = []
    // A fault answers every later request, because the SDK retries throttles, 5xx responses and dropped
    // connections on its own before the caller sees an error.
    let fault: FakeSesFault | null = null

    const server = http.createServer((req, res) => {
        const chunks: Buffer[] = []
        req.on('data', (chunk: Buffer) => chunks.push(chunk))
        req.on('end', () => {
            if (fault === 'drop-connection') {
                req.socket.destroy()
                return
            }
            if (fault === 'no-answer') {
                return
            }
            if (fault === 'stalled-body') {
                res.writeHead(200, { 'content-type': 'application/json' }).write('{"MessageId":')
                return
            }
            if (fault) {
                respond(res, fault.status, { message: fault.message }, fault.type)
                return
            }
            if (req.method !== 'POST' || req.url !== SEND_EMAIL_PATH) {
                respond(res, 404, { message: `No route for ${req.method} ${req.url}` }, 'NotFoundException')
                return
            }

            const request = parseJSON(Buffer.concat(chunks).toString())
            const configurationSetName: string | undefined = request.ConfigurationSetName
            const configurationSet =
                configurationSetName === undefined ? { tracking: false } : configurationSets[configurationSetName]
            if (!configurationSet) {
                respond(
                    res,
                    404,
                    { message: `Configuration set <${configurationSetName}> does not exist.` },
                    'NotFoundException'
                )
                return
            }
            const simple = request.Content?.Simple
            const contentParts = [simple?.Subject, simple?.Body?.Text, simple?.Body?.Html]
            if (!simple?.Subject || contentParts.some((part) => part !== undefined && typeof part.Data !== 'string')) {
                respond(res, 400, { message: 'Every subject and body part needs Data.' }, 'BadRequestException')
                return
            }
            if (!isNameValueList(request.EmailTags) || !isNameValueList(simple.Headers)) {
                respond(res, 400, { message: 'Every tag and header needs a Name and a Value.' }, 'BadRequestException')
                return
            }
            const attachments = toAttachments(simple.Attachments)
            if (typeof attachments === 'string') {
                respond(res, 400, { message: attachments }, 'BadRequestException')
                return
            }

            const messageId = `fake-ses-${sent.length + 1}`
            sent.push({
                messageId,
                from: request.FromEmailAddress,
                feedbackForwardingAddress: request.FeedbackForwardingEmailAddress,
                to: request.Destination?.ToAddresses ?? [],
                cc: request.Destination?.CcAddresses,
                bcc: request.Destination?.BccAddresses,
                replyTo: request.ReplyToAddresses,
                subject: simple.Subject?.Data,
                text: simple.Body?.Text?.Data,
                html: simple.Body?.Html?.Data,
                charsets: {
                    subject: simple.Subject?.Charset,
                    text: simple.Body?.Text?.Charset,
                    html: simple.Body?.Html?.Charset,
                },
                headers: toRecord(simple.Headers),
                tags: toRecord(request.EmailTags),
                tenant: request.TenantName,
                configurationSet: configurationSetName,
                tracked: configurationSet.tracking,
                attachments,
            })
            respond(res, 200, { MessageId: messageId })
        })
    })
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const { port } = server.address() as AddressInfo

    // The SDK signs every request, so it needs credentials even though the fake accepts any. It ignores
    // the key pair while AWS_PROFILE is set, so the profile is unset until the fake closes.
    const credentialVariables = {
        AWS_ACCESS_KEY_ID: 'fake-ses',
        AWS_SECRET_ACCESS_KEY: 'fake-ses',
        AWS_PROFILE: undefined,
    }
    const setVariables = (values: Record<string, string | undefined>): void =>
        Object.entries(values).forEach(([name, value]) => {
            if (value === undefined) {
                delete process.env[name]
            } else {
                process.env[name] = value
            }
        })
    const previousCredentials = Object.fromEntries(
        Object.keys(credentialVariables).map((name) => [name, process.env[name]])
    )
    setVariables(credentialVariables)

    return {
        endpoint: `http://127.0.0.1:${port}`,
        sent,
        failWith: (next) => {
            fault = next
        },
        close: async () => {
            setVariables(previousCredentials)
            server.closeAllConnections()
            await new Promise<void>((resolve) => server.close(() => resolve()))
        },
    }
}
