const WEBAUTHN_ERROR_MESSAGES: Record<string, string> = {
    NotAllowedError: 'Operation was cancelled or timed out.',
    InvalidStateError: 'This passkey is already registered.',
    SecurityError: 'Security error occurred. Please try again.',
    AbortError: 'Operation was cancelled.',
    UnknownError: "Your device couldn't save the passkey. Try again, or use another device or a security key.",
    NotReadableError: "Your device couldn't read the passkey. Try again, or use another device or a security key.",
    ConstraintError: 'Your device cannot create a passkey that meets our security requirements. Try another device.',
}

const WEBAUTHN_CANCELLATION_ERROR_NAMES = new Set(['NotAllowedError', 'AbortError'])

// SimpleWebAuthn sometimes wraps the browser error under an `error` property, so read both levels.
export function getWebAuthnErrorName(error: unknown): string | null {
    if (!error || typeof error !== 'object') {
        return null
    }
    const name = (error as { name?: unknown }).name
    if (typeof name === 'string') {
        return name
    }
    const nestedName = (error as { error?: { name?: unknown } }).error?.name
    return typeof nestedName === 'string' ? nestedName : null
}

// SimpleWebAuthn surfaces user cancellations and authenticator timeouts as
// `NotAllowedError`/`AbortError`. These are expected outcomes, so never display them as errors
// and never capture them in exception tracking.
export function isWebAuthnCancellation(error: unknown): boolean {
    const name = getWebAuthnErrorName(error)
    return name !== null && WEBAUTHN_CANCELLATION_ERROR_NAMES.has(name)
}

export function getPasskeyErrorMessage(error: any, defaultMessage?: string): string {
    const name = getWebAuthnErrorName(error)
    if (name && WEBAUTHN_ERROR_MESSAGES[name]) {
        return WEBAUTHN_ERROR_MESSAGES[name]
    }

    if (error?.detail) {
        return error.detail
    }

    if (error?.message) {
        return error.message
    }

    return defaultMessage ?? 'Passkey authentication failed. Please try again.'
}
