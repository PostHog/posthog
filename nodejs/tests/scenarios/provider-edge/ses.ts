import addressparser from 'nodemailer/lib/addressparser'
import { z } from 'zod'

import { TRACKING_CODE_HEADER_NAME } from '~/cdp/services/messaging/helpers/tracking-code'

import { SesStatusAnswer } from './faults'
import { problemsOf } from './problems'

export const SEND_EMAIL_PATH = '/v2/email/outbound-emails'
export const UNIT_EMAIL_DOMAIN = 'www.example.com'

export type ConfigurationSets = Record<string, { tracking: boolean }>

export interface SesAttachment {
    filename: string
    contentType: string | undefined
    contentId: string | undefined
    inline: boolean
    bytes: Buffer
}

export interface SesMessage {
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
    tracked: boolean | undefined
    attachments: SesAttachment[]
}

export type SesRequest = { message: Omit<SesMessage, 'messageId'> } | { error: SesStatusAnswer }

const Part = z.object({ Data: z.string(), Charset: z.string().optional() })
const NameValues = z.array(z.object({ Name: z.string(), Value: z.string() })).optional()
const Addresses = z.array(z.string()).optional()
const Attachment = z
    .object({
        RawContent: z.string(),
        FileName: z.string(),
        ContentDisposition: z.enum(['ATTACHMENT', 'INLINE']).optional(),
        ContentDescription: z.string().optional(),
        ContentId: z.string().optional(),
        ContentTransferEncoding: z.string().optional(),
        ContentType: z.string().optional(),
    })
    .strict()

const SendEmailRequest = z.object({
    FromEmailAddress: z.string(),
    FeedbackForwardingEmailAddress: z.string().optional(),
    Destination: z.object({ ToAddresses: Addresses, CcAddresses: Addresses, BccAddresses: Addresses }).optional(),
    ReplyToAddresses: Addresses,
    Content: z.object({
        Simple: z.object({
            Subject: Part,
            Body: z.object({ Text: Part.optional(), Html: Part.optional() }).optional(),
            Headers: NameValues,
            Attachments: z.array(Attachment).optional(),
        }),
    }),
    EmailTags: NameValues,
    TenantName: z.string().optional(),
    ConfigurationSetName: z.string().optional(),
})

function toRecord(entries: z.infer<typeof NameValues>): Record<string, string> {
    return Object.fromEntries((entries ?? []).map(({ Name, Value }) => [Name, Value]))
}

function configurationSetOf(
    name: string | undefined,
    known: ConfigurationSets | undefined
): { tracking: boolean | undefined } | undefined {
    if (known === undefined) {
        return { tracking: undefined }
    }
    if (name === undefined) {
        return { tracking: false }
    }
    return known[name]
}

export function readSendEmail(body: unknown, configurationSets: ConfigurationSets | undefined): SesRequest {
    const parsed = SendEmailRequest.safeParse(body)
    if (!parsed.success) {
        return {
            error: {
                status: 400,
                type: 'BadRequestException',
                message: problemsOf(parsed.error, 'request').join('; '),
            },
        }
    }
    const request = parsed.data
    const configurationSet = configurationSetOf(request.ConfigurationSetName, configurationSets)
    if (!configurationSet) {
        return {
            error: {
                status: 404,
                type: 'NotFoundException',
                message: `Configuration set <${request.ConfigurationSetName}> does not exist.`,
            },
        }
    }
    const { Subject, Body, Headers, Attachments } = request.Content.Simple
    return {
        message: {
            from: request.FromEmailAddress,
            feedbackForwardingAddress: request.FeedbackForwardingEmailAddress,
            to: request.Destination?.ToAddresses ?? [],
            cc: request.Destination?.CcAddresses,
            bcc: request.Destination?.BccAddresses,
            replyTo: request.ReplyToAddresses,
            subject: Subject.Data,
            text: Body?.Text?.Data,
            html: Body?.Html?.Data,
            charsets: { subject: Subject.Charset, text: Body?.Text?.Charset, html: Body?.Html?.Charset },
            headers: toRecord(Headers),
            tags: toRecord(request.EmailTags),
            tenant: request.TenantName,
            configurationSet: request.ConfigurationSetName,
            tracked: configurationSet.tracking,
            attachments: (Attachments ?? []).map((attachment) => ({
                filename: attachment.FileName,
                contentType: attachment.ContentType,
                contentId: attachment.ContentId,
                inline: attachment.ContentDisposition === 'INLINE',
                bytes: Buffer.from(attachment.RawContent, 'base64'),
            })),
        },
    }
}

export function addressesOf(mailboxes: string[]): string[] {
    return mailboxes.flatMap((mailbox) => addressparser(mailbox, { flatten: true }).map(({ address }) => address))
}

export function unitIdOf(addresses: string[]): string | undefined {
    const suffix = `@${UNIT_EMAIL_DOMAIN}`
    return addresses.find((address) => address.endsWith(suffix))?.slice(0, -suffix.length)
}

export function trackingCodeOf(message: Omit<SesMessage, 'messageId'>): string | undefined {
    return message.headers[TRACKING_CODE_HEADER_NAME]
}
