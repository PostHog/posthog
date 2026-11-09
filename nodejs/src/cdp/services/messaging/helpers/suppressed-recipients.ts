import addressparser from 'nodemailer/lib/addressparser'

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

type ParsedAddress = { email: string; name?: string }

// Tab, line feed and carriage return are left out: they separate the entries of an address list.
const CONTROL_CHARACTER = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/
const CONTROL_CHARACTERS = new RegExp(CONTROL_CHARACTER.source, 'g')
// U+2400 to U+241F picture the C0 controls in order, and U+2421 pictures DEL.
const CONTROL_PICTURES = /[␀-␟␡]/g

const toControlPicture = (char: string): string =>
    String.fromCharCode(char === '\x7F' ? 0x2421 : 0x2400 + char.charCodeAt(0))

const escapeControlPicture = (picture: string): string =>
    `\\u${(picture === '␡' ? 0x7f : picture.charCodeAt(0) - 0x2400).toString(16).padStart(4, '0')}`

// addressparser drops control characters, so they go in as pictures and stay visible in the parsed addresses.
const mailboxesWithControlCharacters = (value: string | undefined, isList: boolean): string[] => {
    if (typeof value !== 'string' || !CONTROL_CHARACTER.test(value)) {
        return []
    }
    const pictured = value.replace(CONTROL_CHARACTERS, toControlPicture)
    const mailboxes = isList ? addressparser(pictured, { flatten: true }).map((entry) => entry.address) : [pictured]
    return mailboxes.filter((mailbox) => mailbox !== mailbox.replace(CONTROL_PICTURES, ''))
}

export const fieldsWithControlCharacters = ({ to, cc, bcc }: EmailRecipients): string[] =>
    Object.entries({
        To: mailboxesWithControlCharacters(to?.email, false),
        CC: mailboxesWithControlCharacters(cc, true),
        BCC: mailboxesWithControlCharacters(bcc, true),
    }).flatMap(([field, mailboxes]) =>
        mailboxes.length > 0
            ? [`${field} "${mailboxes.join(', ').replace(CONTROL_PICTURES, escapeControlPicture)}"`]
            : []
    )

// The suppression list stores bare addresses, so a quoted local part (`"jo"@x.com`) is checked unquoted.
export const unquoteMailbox = (address: string): string => {
    const at = address.lastIndexOf('@')
    const local = address.slice(0, at).trim()
    if (at < 0 || !/^".*"$/.test(local)) {
        return address.trim()
    }
    return `${local.slice(1, -1).replace(/\\(.)/g, '$1')}@${address.slice(at + 1).trim()}`
}

// addressparser drops the quotes from a bare quoted local part, so they are added back for delivery.
export const quoteMailbox = (email: string): string => {
    const at = email.lastIndexOf('@')
    const local = email.slice(0, at)
    if (at < 0 || /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+$/.test(local)) {
        return email
    }
    return `"${local.replace(/(["\\])/g, '\\$1')}"${email.slice(at)}`
}

// Parses the list the way SES does (RFC 5322), so quoted display names, comments and commas inside
// quotes never hide the mailbox that receives the email.
const parseAddressList = (value: string | undefined): ParsedAddress[] =>
    typeof value === 'string'
        ? addressparser(value, { flatten: true })
              .filter((entry) => entry.address.trim().length > 0)
              .map((entry) => {
                  const name = entry.name.replace(/[\x00-\x1F\x7F"\\<>,;]/g, '').trim()
                  return { email: unquoteMailbox(entry.address), ...(name ? { name } : {}) }
              })
        : []

// Rebuilt from the parsed parts, so delivery sends to exactly the address the suppression check saw.
const formatAddress = ({ email, name }: ParsedAddress): string =>
    name ? `"${name}" <${quoteMailbox(email)}>` : quoteMailbox(email)

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
 * Kept cc and bcc entries are rewritten from their parsed parts, so the consent check, the send caps
 * and SES all see the address that was checked here.
 */
export const removeSuppressedRecipients = async (
    recipients: EmailRecipients,
    isSuppressed: (email: string) => Promise<boolean>
): Promise<SuppressedRecipientsResult> => {
    const removed: string[] = []
    const keepDeliverable = async (entries: ParsedAddress[]): Promise<ParsedAddress[]> => {
        const suppressed = await Promise.all(entries.map((entry) => isSuppressed(entry.email)))
        return entries.filter((entry, i) => {
            if (suppressed[i]) {
                removed.push(entry.email)
            }
            return !suppressed[i]
        })
    }
    const formatList = (original: string | undefined, entries: ParsedAddress[]): string | undefined =>
        original === undefined ? undefined : entries.map(formatAddress).join(', ')

    const toEmail = recipients.to?.email ? unquoteMailbox(recipients.to.email) : undefined
    const toSuppressed = !!toEmail && (await isSuppressed(toEmail))
    if (toEmail && toSuppressed) {
        removed.push(toEmail)
    }
    const ccEntries = await keepDeliverable(parseAddressList(recipients.cc))
    const bccEntries = await keepDeliverable(parseAddressList(recipients.bcc))

    if (removed.length === 0) {
        return {
            skip: false,
            cc: formatList(recipients.cc, ccEntries),
            bcc: formatList(recipients.bcc, bccEntries),
            removed,
        }
    }
    if (toSuppressed && ccEntries.length === 0) {
        return { skip: true, removed }
    }
    const promoted = toSuppressed ? ccEntries.shift() : undefined
    const promotedTo = promoted ? { ...promoted, email: quoteMailbox(promoted.email) } : undefined
    return {
        skip: false,
        promotedTo,
        cc: ccEntries.map(formatAddress).join(', '),
        bcc: bccEntries.map(formatAddress).join(', '),
        removed,
    }
}
