import { PENDING_OAUTH_CONNECTION_COOKIE } from './pendingOAuthConnectionLogic'

export const PENDING_OAUTH_CONNECTION_FIXTURE = {
    client_name: 'Claude',
    client_id: 'https://claude.example.com/.well-known/oauth-client',
    logo_uri: 'https://claude.example.com/logo.png',
    redirect_host: 'claude.example.com',
}

/** A string is written raw, so a test can pass a malformed value. An object is encoded the way
 * the backend encodes it. */
export function setPendingOAuthConnectionCookie(connection: object | string | null): void {
    if (connection === null) {
        document.cookie = `${PENDING_OAUTH_CONNECTION_COOKIE}=; max-age=0; path=/`
        return
    }
    const raw = typeof connection === 'string' ? connection : encodeURIComponent(JSON.stringify(connection))
    document.cookie = `${PENDING_OAUTH_CONNECTION_COOKIE}=${raw}; path=/`
}
