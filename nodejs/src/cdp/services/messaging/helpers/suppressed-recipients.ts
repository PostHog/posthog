export type EmailRecipients = {
    to?: { email?: string }
    cc?: string
    bcc?: string
}

export type SuppressedRecipientsResult = {
    // True when `to` is suppressed and no cc address can take its place.
    skip: boolean
    // Set when `to` is suppressed and the first deliverable cc address replaces it.
    promotedTo?: { email: string; name?: string }
    cc?: string
    bcc?: string
    removed: string[]
}

// One entry of a comma-separated address list, in plain `email` or RFC-822 `"Name" <email>` form.
const parseAddressEntry = (entry: string): { email: string; name?: string } => {
    const bracketed = entry.match(/^(.*)<([^>]+)>\s*$/)
    if (!bracketed) {
        return { email: entry.trim() }
    }
    const name = bracketed[1]
        .trim()
        .replace(/^"(.*)"$/, '$1')
        .trim()
    return { email: bracketed[2].trim(), ...(name ? { name } : {}) }
}

const splitAddressList = (value: string | undefined): string[] =>
    typeof value === 'string'
        ? value
              .split(',')
              .map((entry) => entry.trim())
              .filter((entry) => entry.length > 0)
        : []

/**
 * Removes the addresses on the team's suppression list from an email's recipients. SES delivers to
 * every address in to, cc and bcc, so each one is checked.
 *
 * Suppressed cc and bcc addresses are dropped, so one bounced address on a shared thread does not
 * stop delivery to everyone else. When `to` is suppressed, the first deliverable cc address becomes
 * `to`. This keeps an email addressed to a group (for example, every admin of an account) going
 * after the first address bounces. A bcc address is never promoted, because that would show a
 * hidden recipient to everyone else on the email.
 *
 * Kept cc and bcc entries stay in their original form.
 */
export const removeSuppressedRecipients = async (
    recipients: EmailRecipients,
    isSuppressed: (email: string) => Promise<boolean>
): Promise<SuppressedRecipientsResult> => {
    const removed: string[] = []
    const keepDeliverable = async (entries: string[]): Promise<string[]> => {
        const suppressed = await Promise.all(entries.map((entry) => isSuppressed(parseAddressEntry(entry).email)))
        return entries.filter((entry, i) => {
            if (suppressed[i]) {
                removed.push(parseAddressEntry(entry).email)
            }
            return !suppressed[i]
        })
    }

    const toEmail = recipients.to?.email?.trim()
    const toSuppressed = !!toEmail && (await isSuppressed(toEmail))
    if (toEmail && toSuppressed) {
        removed.push(toEmail)
    }
    const ccEntries = await keepDeliverable(splitAddressList(recipients.cc))
    const bccEntries = await keepDeliverable(splitAddressList(recipients.bcc))

    if (removed.length === 0) {
        return { skip: false, cc: recipients.cc, bcc: recipients.bcc, removed }
    }
    if (toSuppressed && ccEntries.length === 0) {
        return { skip: true, removed }
    }
    const promotedTo = toSuppressed ? parseAddressEntry(ccEntries.shift()!) : undefined
    return { skip: false, promotedTo, cc: ccEntries.join(', '), bcc: bccEntries.join(', '), removed }
}
