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

export function getPasskeyErrorMessage(error: any, defaultMessage?: string): string {
    if (error?.name && WEBAUTHN_ERROR_MESSAGES[error.name]) {
        return WEBAUTHN_ERROR_MESSAGES[error.name]
    }

    if (error?.detail) {
        return error.detail
    }

    if (error?.message) {
        return error.message
    }

    return defaultMessage ?? 'Passkey authentication failed. Please try again.'
}
