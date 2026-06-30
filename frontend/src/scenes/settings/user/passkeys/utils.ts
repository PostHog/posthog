const WEBAUTHN_ERROR_MESSAGES: Record<string, string> = {
    NotAllowedError: 'Operation was cancelled or timed out.',
    InvalidStateError: 'This passkey is already registered.',
    SecurityError: 'Security error occurred. Please try again.',
    AbortError: 'Operation was cancelled.',
}

const WEBAUTHN_CANCELLATION_ERROR_NAMES = new Set(['NotAllowedError', 'AbortError'])

// SimpleWebAuthn surfaces user cancellations, authenticator timeouts, and
// environmental refusals (e.g. Chromium blocking WebAuthn on pages with TLS
// certificate errors) as `NotAllowedError`/`AbortError`. The original
// DOMException can sit directly on the error, under an `error` property, or —
// in SimpleWebAuthn v13 — nested under `cause` on the wrapping `WebAuthnError`.
// All of these are expected outcomes — never display them as errors or capture
// them in exception tracking.
function matchesCancellationName(name: unknown): boolean {
    return typeof name === 'string' && WEBAUTHN_CANCELLATION_ERROR_NAMES.has(name)
}

export function isWebAuthnCancellation(error: unknown): boolean {
    if (!error || typeof error !== 'object') {
        return false
    }
    const {
        name,
        error: nested,
        cause,
    } = error as {
        name?: unknown
        error?: { name?: unknown }
        cause?: { name?: unknown }
    }
    return (
        matchesCancellationName(name) || matchesCancellationName(nested?.name) || matchesCancellationName(cause?.name)
    )
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
