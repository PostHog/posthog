export const LOCALSTORAGE_KEY = '_postHogToolbarParams'
export const OAUTH_LOCALSTORAGE_KEY = '_postHogToolbarOAuth'
export const PKCE_STORAGE_KEY = '_postHogToolbarPKCE'

export interface ToolbarAuthParams {
    code: string
    clientId: string
}

/**
 * Read `__posthog_toolbar=code:…,client_id:…` from the URL hash without modifying the URL.
 * Returns the matched params if found, or null.
 */
export function readToolbarAuthHash(): ToolbarAuthParams | null {
    let hash: string
    try {
        hash = decodeURIComponent(window.location.hash)
    } catch {
        hash = window.location.hash
    }
    const codeMatch = hash.match(/__posthog_toolbar=code:([^,]+),client_id:([^,&]+)/)
    if (!codeMatch) {
        return null
    }
    return {
        code: codeMatch[1],
        clientId: codeMatch[2],
    }
}

/**
 * Remove `__posthog_toolbar=code:…,client_id:…` from the URL hash.
 *
 * Separated from reading so that the URL modification (history.replaceState)
 * can be deferred — some SPAs watch for URL changes and re-render the page,
 * which can destroy the toolbar mid-initialization if the hash is cleaned
 * synchronously during mount.
 */
export function cleanToolbarAuthHash(): void {
    let hash: string
    try {
        hash = decodeURIComponent(window.location.hash)
    } catch {
        hash = window.location.hash
    }
    if (!hash.includes('__posthog_toolbar=')) {
        return
    }

    const cleanHash = hash
        .replace(/__posthog_toolbar=[^&]*/g, '')
        .replace(/&&+/g, '&')
        .replace(/&$/, '')
        .replace(/^#&/, '#')
        .replace(/^#$/, '')
    history.replaceState(null, '', location.pathname + location.search + (cleanHash || ''))
}

export async function generatePKCE(): Promise<{ verifier: string; challenge: string }> {
    const bytes = new Uint8Array(48)
    crypto.getRandomValues(bytes)
    const verifier = btoa(String.fromCharCode(...bytes))
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/g, '')
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
    const challenge = btoa(String.fromCharCode(...new Uint8Array(digest)))
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/g, '')
    return { verifier, challenge }
}
