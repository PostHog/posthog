// PKCE (RFC 7636) helpers for the OAuth authorization-code flow. Ported from the
// PostHog Code desktop app, using the browser's Web Crypto API.

function base64UrlEncode(bytes: Uint8Array): string {
    let binary = ''
    for (const byte of bytes) {
        binary += String.fromCharCode(byte)
    }
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/** A high-entropy random string kept on the client and presented at token exchange. */
export function generateCodeVerifier(): string {
    const bytes = new Uint8Array(32)
    window.crypto.getRandomValues(bytes)
    return base64UrlEncode(bytes)
}

/** The S256 challenge derived from the verifier, sent on the authorize request. */
export async function generateCodeChallenge(verifier: string): Promise<string> {
    const data = new TextEncoder().encode(verifier)
    const digest = await window.crypto.subtle.digest('SHA-256', data)
    return base64UrlEncode(new Uint8Array(digest))
}

/** Opaque CSRF value round-tripped through the `state` param to bind the callback to this flow. */
export function generateState(): string {
    const bytes = new Uint8Array(16)
    window.crypto.getRandomValues(bytes)
    return base64UrlEncode(bytes)
}
