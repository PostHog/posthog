/** The webmail a verification email went to, detected by the backend when it sends a code.
 * pinned: values of `inbox_provider` in the signup and login responses (posthog/inbox_providers.py) */
export type InboxProvider = 'gmail' | 'outlook' | 'microsoft_365' | 'yahoo' | 'icloud' | 'proton'

type InboxProviderLink = {
    name: string
    url: (email: string | null) => string
}

// Searches every folder, spam included. `authuser` picks the account the code went to.
const GMAIL_RECENT_MAIL_SEARCH = '#search/in%3Aanywhere+newer_than%3A1h'

const INBOX_PROVIDER_LINKS: Record<InboxProvider, InboxProviderLink> = {
    gmail: {
        name: 'Gmail',
        url: (email) =>
            `https://mail.google.com/mail/${email ? `?authuser=${encodeURIComponent(email)}` : ''}${GMAIL_RECENT_MAIL_SEARCH}`,
    },
    outlook: { name: 'Outlook', url: () => 'https://outlook.live.com/mail/0/' },
    microsoft_365: { name: 'Outlook', url: () => 'https://outlook.office.com/mail/' },
    yahoo: { name: 'Yahoo Mail', url: () => 'https://mail.yahoo.com/' },
    icloud: { name: 'iCloud Mail', url: () => 'https://www.icloud.com/mail/' },
    proton: { name: 'Proton Mail', url: () => 'https://mail.proton.me/u/0/inbox' },
}

export function parseInboxProvider(value: unknown): InboxProvider | null {
    return typeof value === 'string' && Object.hasOwn(INBOX_PROVIDER_LINKS, value) ? (value as InboxProvider) : null
}

export function inboxProviderLink(provider: InboxProvider, email: string | null): { name: string; url: string } {
    const link = INBOX_PROVIDER_LINKS[provider]
    return { name: link.name, url: link.url(email) }
}
