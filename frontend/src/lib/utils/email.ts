/**
 * A port of Django 5.2's `EmailValidator`, which is what `serializers.EmailField` runs on
 * `api/login` and `api/signup`. Keeping the two in step is the whole point: an address this
 * accepts but the server rejects comes back as a field-level 400, which the error reporting
 * gate now excuses, so the user would be left with an error nobody is counting.
 *
 * Django writes the host patterns with lookbehind. The equivalent below spells the same rule
 * as "first and last character is not a dash", because an unsupported regex would throw while
 * the module loads and take the whole login page with it on an older browser.
 */

/** Unicode letters range, per Django's `DomainNameValidator.ul`. */
const UL = '\\u00a1-\\uffff'

/** A host label: 1-63 characters, no leading or trailing dash (RFC 1034 section 3.1). */
const LABEL = `[a-z${UL}0-9](?:[a-z${UL}0-9-]{0,61}[a-z${UL}0-9])?`

/** A top-level domain: 2-63 letters, or a punycode label. Digits are not allowed here. */
const TLD = `\\.(?:[a-z${UL}][a-z${UL}-]{0,61}[a-z${UL}]|xn--[a-z0-9]{1,59})`

const DOMAIN_REGEX = new RegExp(`^${LABEL}(?:\\.${LABEL})*${TLD}$`, 'i')

/**
 * The bracketed IPv4/IPv6 form from SMTP 4.1.3. Django validates the address inside the
 * brackets as well; this accepts any plausible one, so at worst a malformed literal reaches
 * the server, which is the safe direction — the other way blocks a submit that would work.
 */
const IP_LITERAL_REGEX = /^\[[a-f0-9:.]+\]$/i

/** The local part: a dot-atom, or a quoted string. */
const LOCAL_PART_REGEX =
    // oxlint-disable-next-line no-control-regex
    /^(?:[-!#$%&'*+/=?^_`{}|~0-9a-z]+(?:\.[-!#$%&'*+/=?^_`{}|~0-9a-z]+)*|"(?:[\x01-\x08\x0b\x0c\x0e-\x1f!#-\x5b\x5d-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])*")$/i

/** The one dotless domain Django accepts, for a self-hosted instance on the local machine. */
const ALLOWED_DOMAIN = 'localhost'

/** The longest an address can be, per RFC 3696 section 3. */
const MAX_LENGTH = 320

/** The message both the login and the signup form show for an address the server would reject. */
export const INVALID_EMAIL_MESSAGE = 'Please use a valid email address'

/**
 * Whether the server would accept this address, so the form can reject a malformed one instead
 * of letting `api/login` or `api/signup` answer with a field-level 400.
 *
 * Surrounding whitespace is trimmed first, because the serializers trim it too: rejecting a
 * pasted address with a trailing space would block a submit that would have succeeded.
 */
export function isValidEmail(email: string): boolean {
    const address = email.trim()
    const separator = address.lastIndexOf('@')
    if (separator === -1 || address.length > MAX_LENGTH) {
        return false
    }
    const domainPart = address.slice(separator + 1)
    return (
        LOCAL_PART_REGEX.test(address.slice(0, separator)) &&
        (domainPart === ALLOWED_DOMAIN || DOMAIN_REGEX.test(domainPart) || IP_LITERAL_REGEX.test(domainPart))
    )
}
