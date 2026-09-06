const WEBAUTHN_ERROR_MESSAGES: Record<string, string> = {
    NotAllowedError: 'Operation was cancelled or timed out.',
    InvalidStateError: 'This passkey is already registered.',
    SecurityError: 'Security error occurred. Please try again.',
    AbortError: 'Operation was cancelled.',
}

const WEBAUTHN_CANCELLATION_ERROR_NAMES = new Set(['NotAllowedError', 'AbortError'])

// SimpleWebAuthn and WebKit surface user cancellations and authenticator
// timeouts as `NotAllowedError`/`AbortError`, sometimes wrapped one or more
// levels deep under an `error` or `cause` property (WebKit wraps a
// `DOMException` cancellation under `cause`). These are expected outcomes —
// never display them as errors or capture them in exception tracking.
export function isWebAuthnCancellation(error: unknown): boolean {
    let current = error
    // Cap the walk to guard against cyclic references.
    for (let depth = 0; depth < 10; depth++) {
        if (!current || typeof current !== 'object') {
            return false
        }
        const name = (current as { name?: unknown }).name
        if (typeof name === 'string' && WEBAUTHN_CANCELLATION_ERROR_NAMES.has(name)) {
            return true
        }
        const wrapped = current as { error?: unknown; cause?: unknown }
        current = wrapped.cause ?? wrapped.error
    }
    return false
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
