import { ApiError } from 'lib/api-error'

const WEBAUTHN_ERROR_MESSAGES: Record<string, string> = {
    NotAllowedError: 'Operation was cancelled or timed out.',
    InvalidStateError: 'This passkey is already registered.',
    SecurityError: 'Security error occurred. Please try again.',
    AbortError: 'Operation was cancelled.',
}

const WEBAUTHN_CANCELLATION_ERROR_NAMES = new Set(['NotAllowedError', 'AbortError'])

// SimpleWebAuthn surfaces user cancellations and authenticator timeouts as
// `NotAllowedError`/`AbortError`, sometimes wrapped under an `error` property.
// These are expected outcomes — never display them as errors or capture them
// in exception tracking.
export function isWebAuthnCancellation(error: unknown): boolean {
    if (!error || typeof error !== 'object') {
        return false
    }
    const name = (error as { name?: unknown }).name
    if (typeof name === 'string' && WEBAUTHN_CANCELLATION_ERROR_NAMES.has(name)) {
        return true
    }
    const nestedName = (error as { error?: { name?: unknown } }).error?.name
    return typeof nestedName === 'string' && WEBAUTHN_CANCELLATION_ERROR_NAMES.has(nestedName)
}

// A response that never arrived (`status` undefined, e.g. a NetworkError) or a 5xx is a server,
// gateway, or network hiccup rather than a bad request. api.ts documents
// `status === undefined || status >= 500` as the recovery check; passkey login mirrors it to show
// a retry message instead of a raw internal error string.
export function isTransientPasskeyServerError(error: unknown): boolean {
    return error instanceof ApiError && (error.status === undefined || error.status >= 500)
}

export function getPasskeyErrorMessage(error: any, defaultMessage?: string): string {
    if (error?.name && WEBAUTHN_ERROR_MESSAGES[error.name]) {
        return WEBAUTHN_ERROR_MESSAGES[error.name]
    }

    // Only trust a server-provided `detail`. Falling back to `error.message` would surface the
    // raw internal fallback string (e.g. "Non-OK response [POST ...] (status 503)") to the user.
    if (error?.detail) {
        return error.detail
    }

    return defaultMessage ?? 'Passkey authentication failed. Please try again.'
}
