import { TRACKING_CODE_HEADER_NAME } from '~/cdp/services/messaging/helpers/tracking-code'

import { SesStatusAnswer } from './faults'

export const SEND_EMAIL_PATH = '/v2/email/outbound-emails'
export const UNIT_EMAIL_DOMAIN = 'www.example.com'

export type ConfigurationSets = Record<string, { tracking: boolean }>

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
}

export type SesRequest = { message: Omit<SesMessage, 'messageId'> } | { error: SesStatusAnswer }

type NameValueList = { Name: string; Value: string }[]

function isNameValueList(entries: unknown): entries is NameValueList | undefined {
    return (
        entries === undefined ||
        (Array.isArray(entries) &&
            entries.every((entry) => typeof entry?.Name === 'string' && typeof entry?.Value === 'string'))
    )
}

function isAddressList(addresses: unknown): addresses is string[] | undefined {
    return addresses === undefined || (Array.isArray(addresses) && addresses.every((a) => typeof a === 'string'))
}

function toRecord(entries: NameValueList | undefined): Record<string, string> {
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

export function readSendEmail(
    request: Record<string, any>,
    configurationSets: ConfigurationSets | undefined
): SesRequest {
    const configurationSetName: string | undefined = request?.ConfigurationSetName
    const configurationSet = configurationSetOf(configurationSetName, configurationSets)
    if (!configurationSet) {
        return {
            error: {
                status: 404,
                type: 'NotFoundException',
                message: `Configuration set <${configurationSetName}> does not exist.`,
            },
        }
    }
    const simple = request.Content?.Simple
    const contentParts = [simple?.Subject, simple?.Body?.Text, simple?.Body?.Html]
    if (!simple?.Subject || contentParts.some((part) => part !== undefined && typeof part.Data !== 'string')) {
        return {
            error: { status: 400, type: 'BadRequestException', message: 'Every subject and body part needs Data.' },
        }
    }
    if (!isNameValueList(request.EmailTags) || !isNameValueList(simple.Headers)) {
        return {
            error: {
                status: 400,
                type: 'BadRequestException',
                message: 'Every tag and header needs a Name and a Value.',
            },
        }
    }
    const destination = request.Destination
    const addressLists = [
        destination?.ToAddresses,
        destination?.CcAddresses,
        destination?.BccAddresses,
        request.ReplyToAddresses,
    ]
    if (!addressLists.every(isAddressList)) {
        return {
            error: { status: 400, type: 'BadRequestException', message: 'Every address list needs to be a list.' },
        }
    }
    return {
        message: {
            from: request.FromEmailAddress,
            feedbackForwardingAddress: request.FeedbackForwardingEmailAddress,
            to: request.Destination?.ToAddresses ?? [],
            cc: request.Destination?.CcAddresses,
            bcc: request.Destination?.BccAddresses,
            replyTo: request.ReplyToAddresses,
            subject: simple.Subject.Data,
            text: simple.Body?.Text?.Data,
            html: simple.Body?.Html?.Data,
            charsets: {
                subject: simple.Subject.Charset,
                text: simple.Body?.Text?.Charset,
                html: simple.Body?.Html?.Charset,
            },
            headers: toRecord(simple.Headers),
            tags: toRecord(request.EmailTags),
            tenant: request.TenantName,
            configurationSet: configurationSetName,
            tracked: configurationSet.tracking,
        },
    }
}

export function addressesOf(mailboxes: string[]): string[] {
    return mailboxes.map((mailbox) => /<([^<>]+)>\s*$/.exec(mailbox)?.[1] ?? mailbox)
}

export function unitIdOf(addresses: string[]): string | undefined {
    const suffix = `@${UNIT_EMAIL_DOMAIN}`
    return addresses.find((address) => address.endsWith(suffix))?.slice(0, -suffix.length)
}

export function trackingCodeOf(message: Omit<SesMessage, 'messageId'>): string | undefined {
    return message.headers[TRACKING_CODE_HEADER_NAME]
}
