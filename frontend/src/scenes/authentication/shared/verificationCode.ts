// Email clients and manual entry can wrap the emailed code in whitespace or invisible characters
// (zero-width family, word joiner, BOM, soft hyphen) or group it as "123-456". Fold compatibility
// digits (e.g. fullwidth) to ASCII and drop that noise so a pasted code matches the server's 6 digits.
const CODE_NOISE_RE = /[\s\u200b-\u200d\u2060\ufeff\u00ad-]/g

export function normalizeVerificationCode(code: string): string {
    return (code ?? '').normalize('NFKC').replace(CODE_NOISE_RE, '')
}

export function isValidVerificationCode(code: string): boolean {
    return /^\d{6}$/.test(code)
}

export function verificationCodeErrorMessage(e: { code?: string; detail?: string }): string {
    if (e.code === 'too_many_attempts') {
        return 'Too many incorrect attempts. Request a new code and try again.'
    }
    if (e.code === 'throttled') {
        return 'Too many attempts. Wait a few minutes and try again.'
    }
    return e.detail || 'This code is invalid or has expired.'
}

// The verify-email page cannot always read the address from the session. A fresh signup and a
// login attempt on an unverified account both land there without one. The form that knows the
// address stores it here, in this browser only, so the page can show it. The helpers use
// try/catch because sessionStorage can throw, for example in private windows with site data blocked.
const PENDING_VERIFICATION_EMAIL_KEY = 'ph_pending_verification_email'

// The value is keyed by user uuid, so a verify page for one account never shows an address
// that an earlier attempt for another account stored in the same tab.
export function setPendingVerificationEmail(uuid: string, email: string): void {
    try {
        sessionStorage.setItem(PENDING_VERIFICATION_EMAIL_KEY, JSON.stringify({ uuid, email }))
    } catch {
        // The page shows the generic copy instead
    }
}

export function getPendingVerificationEmail(uuid: string | null): string | null {
    if (!uuid) {
        return null
    }
    try {
        const raw = sessionStorage.getItem(PENDING_VERIFICATION_EMAIL_KEY)
        if (!raw) {
            return null
        }
        const stored = JSON.parse(raw) as { uuid?: string; email?: string }
        return stored.uuid === uuid ? (stored.email ?? null) : null
    } catch {
        return null
    }
}

export function clearPendingVerificationEmail(): void {
    try {
        sessionStorage.removeItem(PENDING_VERIFICATION_EMAIL_KEY)
    } catch {
        // Nothing to clear when storage is unavailable
    }
}
