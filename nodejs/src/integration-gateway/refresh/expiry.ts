/** Seconds since the Unix epoch (matches Django's `time.time()`). */
export function nowSecs(): number {
    return Date.now() / 1000
}

function asNumber(value: unknown): number | null {
    return typeof value === 'number' && isFinite(value) ? value : null
}

/**
 * Whether an OAuth access token should be proactively refreshed, mirroring Django's
 * `OauthIntegration.access_token_expired`: refresh once past the half-life, i.e.
 * `now > refreshed_at + expires_in - expires_in/2`.
 *
 * Returns false (never refresh) when the timing fields are absent — same as Django, which can't
 * judge expiry without them. Salesforce/Stripe often omit `expires_in`; Django assumes 3600s.
 */
export function accessTokenExpired(kind: string, config: Record<string, any>): boolean {
    const refreshedAt = asNumber(config?.refreshed_at)
    let expiresIn = asNumber(config?.expires_in)

    if (expiresIn === null && (kind === 'salesforce' || kind === 'stripe')) {
        expiresIn = 3600
    }

    if (expiresIn === null || refreshedAt === null) {
        return false
    }
    if (expiresIn <= 0) {
        return false
    }

    const threshold = expiresIn / 2
    return nowSecs() > refreshedAt + expiresIn - threshold
}
