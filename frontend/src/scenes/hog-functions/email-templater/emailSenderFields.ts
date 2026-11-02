import { EmailTemplate, EmailTemplateFrom } from './types'

export type EmailSender = {
    id: number
    display_name?: string
    config?: { domain?: string; email?: string; name?: string; reply_to?: string }
}

export function senderFrom(email: Partial<EmailTemplate>): EmailTemplateFrom {
    return typeof email.from === 'object' && email.from ? email.from : {}
}

export function senderIntegrationFor<T extends { id: number }>(
    email: Partial<EmailTemplate>,
    integrations: T[] | null | undefined
): T | undefined {
    const integrationId = senderFrom(email).integrationId
    return integrationId ? integrations?.find((integration) => integration.id === integrationId) : undefined
}

export function senderDomain(sender: EmailSender | undefined): string {
    return (sender?.config?.domain ?? sender?.config?.email?.split('@')[1] ?? '').toLowerCase()
}

// The address input holds only the part before the @, so the verified domain can't be mistyped.
export function addressLocalPart(address: string | undefined, domain: string): string {
    const suffix = `@${domain}`
    if (address && domain && address.toLowerCase().endsWith(suffix)) {
        return address.slice(0, -suffix.length)
    }
    return address ?? ''
}

// A value that already has an @ was set outside this input, so it is kept whole and checked as is.
export function addressFromLocalPart(localPart: string, domain: string): string | undefined {
    const trimmed = localPart.trim()
    if (!trimmed) {
        return undefined
    }
    return trimmed.includes('@') || !domain ? trimmed : `${trimmed}@${domain}`
}

// Mirrors the send path, which ignores a custom address that fails these checks and sends from the
// sender's own address instead. A templated address is only known at send time, so it isn't checked here.
// The length bound matches the API and keeps the pattern fast.
const SENDER_ADDRESS_MAX_LENGTH = 254
const SENDER_ADDRESS_REGEX = /^[^\s@"<>,;]+@[^\s@"<>,;]+\.[^\s@"<>,;]+$/

export function senderAddressError(address: string | undefined, sender: EmailSender | undefined): string | null {
    const trimmed = address?.trim()
    if (!trimmed || trimmed.includes('{{') || trimmed.includes('{%')) {
        return null
    }
    if (trimmed.length > SENDER_ADDRESS_MAX_LENGTH) {
        return `Use an address of at most ${SENDER_ADDRESS_MAX_LENGTH} characters.`
    }
    if (!SENDER_ADDRESS_REGEX.test(trimmed)) {
        return 'Enter one email address, like hello@example.com.'
    }
    const domain = senderDomain(sender)
    if (domain && trimmed.split('@')[1].toLowerCase() !== domain) {
        return `Use an address on ${domain}, the domain this sender is verified for.`
    }
    return null
}
