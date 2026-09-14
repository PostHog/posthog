/** What Django's `EmailField` accepts. */
const EMAIL_REGEX: RegExp =
    // oxlint-disable-next-line no-control-regex
    /^(?:[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*|"(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21\x23-\x5b\x5d-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])*")@(?:(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?|\[(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[a-z0-9-]*[a-z0-9]:(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21-\x5a\x53-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])+)\])$/i

/** The message both the login and the signup form show for an address the server would reject. */
export const INVALID_EMAIL_MESSAGE = 'Please use a valid email address'

/**
 * Whether the server would accept this address, so the form can reject a malformed one instead of
 * letting `api/login` or `api/signup` answer with a field-level 400.
 *
 * The regex is anchored and case-insensitive on purpose. The unanchored lowercase-only form this
 * replaces rejected a valid capitalized address, and accepted any string that merely contained an
 * address somewhere inside it. Surrounding whitespace is trimmed first, because the serializers
 * trim it too: rejecting a pasted address with a trailing space would block a submit that would
 * have succeeded.
 */
export function isValidEmail(email: string): boolean {
    return EMAIL_REGEX.test(email.trim())
}
