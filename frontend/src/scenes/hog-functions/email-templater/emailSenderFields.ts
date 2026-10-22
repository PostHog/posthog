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

// A workflow can rotate through several senders, kept in `integrationIds`. One sender is in `integrationId` alone.
export function selectedSenderIds(from: EmailTemplateFrom): number[] {
    if (from.integrationIds?.length) {
        return from.integrationIds
    }
    return from.integrationId ? [from.integrationId] : []
}

export function selectedSenders<T extends { id: number }>(
    from: EmailTemplateFrom,
    integrations: T[] | null | undefined
): T[] {
    return selectedSenderIds(from)
        .map((id) => integrations?.find((integration) => integration.id === id))
        .filter((integration): integration is T => !!integration)
}

// The domain every selected sender shares, or empty when they differ or none is selected.
export function sharedSenderDomain(senders: EmailSender[]): string {
    const domains = new Set(senders.map(senderDomain).filter(Boolean))
    return domains.size === 1 ? [...domains][0] : ''
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

export function senderAddressError(
    address: string | undefined,
    senders: EmailSender | EmailSender[] | undefined
): string | null {
    const trimmed = address?.trim()
    if (!trimmed || trimmed.includes('{{') || trimmed.includes('{%')) {
        return null
    }
    if (trimmed.length > SENDER_ADDRESS_MAX_LENGTH) {
        return `Use an address of at most ${SENDER_ADDRESS_MAX_LENGTH} characters.`
    }
    // A send picks one sender per run, so the address must be on the domain of every selected sender.
    // No address can do that across domains, so say so before judging its format.
    const list = Array.isArray(senders) ? senders : senders ? [senders] : []
    const domains = [...new Set(list.map(senderDomain).filter(Boolean))]
    if (domains.length > 1) {
        return 'Your senders are on different domains, so one custom address cannot match them all. Remove the address or pick senders on one domain.'
    }
    if (!SENDER_ADDRESS_REGEX.test(trimmed)) {
        return 'Enter one email address, like hello@example.com.'
    }
    if (domains.length === 1 && trimmed.split('@')[1].toLowerCase() !== domains[0]) {
        const whose = list.length > 1 ? 'your senders are' : 'this sender is'
        return `Use an address on ${domains[0]}, the domain ${whose} verified for.`
    }
    return null
}

// pinned: data-attr values feed autocapture dashboards, e.g. `workflow-email-sender-select`
export type SenderDataAttrPrefix = 'transactional-email' | 'workflow-email'
