import type { StoredSecret } from './types'

export function parseJson(text: string): unknown {
    try {
        return JSON.parse(text)
    } catch {
        return undefined
    }
}

// A stored value hog doesn't recognize, such as one a later version wrote, reads as no login.
export function parseSecret(value: unknown): StoredSecret | undefined {
    const item = value as Record<string, unknown> | null
    if (typeof item?.apiKey === 'string') {
        return { apiKey: item.apiKey }
    }
    if (typeof item?.accessToken === 'string' && typeof item.refreshToken === 'string') {
        return { accessToken: item.accessToken, refreshToken: item.refreshToken }
    }
    return undefined
}
