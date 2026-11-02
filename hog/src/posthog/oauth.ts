import { createHash, randomUUID } from 'node:crypto'

import { HogError } from '@/core/errors'
import { hogFile } from '@/core/paths'
import type { Runtime } from '@/core/runtime'

import { sendRequest, type HttpResponse } from './api'
import type { FileStore, KeychainStore, OAuthCredential } from './credential-store'
import { readLogin, writeLogin } from './logins'
import { readSettings } from './settings'

// hog's CIMD client ID: the URL of its client metadata document, which PostHog fetches.
export const HOG_CLIENT_ID = 'https://posthog.com/.well-known/oauth/hog/client-metadata.json'

const REQUEST_TIMEOUT_MS = 30_000
// Refresh this long before the access token expires, so it doesn't expire during a command.
// A command resolves its credentials once, so the margin also covers a command that runs for minutes.
const REFRESH_MARGIN_MS = 10 * 60_000
// A lock older than this belongs to a process that died before it removed it. A live owner can hold
// the lock through a keychain read, a token request and a keychain write, so the limit is longer than
// all three timeouts together.
const LOCK_STALE_MS = 180_000
const LOCK_POLL_MS = 250

export interface TokenResponse {
    access_token?: string
    refresh_token?: string
    expires_in?: number
    scope?: string
    scoped_teams?: number[]
}

// OAuth endpoints take form-encoded requests, unlike the rest of PostHog's API.
export function oauthPost(
    runtime: Runtime,
    host: string,
    path: string,
    form: Record<string, string>,
    timeoutMs = REQUEST_TIMEOUT_MS
): Promise<HttpResponse> {
    return sendRequest(runtime.fetch, new URL(path, `${host.replace(/\/+$/, '')}/`), {
        method: 'POST',
        form,
        timeoutMs,
    })
}

// Fields the response leaves out keep the values of `previous`, so a refresh that doesn't rotate the
// refresh token keeps the old one.
export function credentialFromTokens(
    runtime: Runtime,
    body: TokenResponse,
    previous: Pick<OAuthCredential, 'host' | 'projectId' | 'refreshToken' | 'scopes'> & { loginId?: string }
): OAuthCredential {
    if (!body.access_token || body.expires_in === undefined) {
        throw new HogError(
            'unexpected_response',
            'PostHog answered without an access token.',
            'Run `hog auth login` to log in again.'
        )
    }
    return {
        type: 'oauth',
        host: previous.host,
        projectId: previous.projectId,
        accessToken: body.access_token,
        refreshToken: body.refresh_token ?? previous.refreshToken,
        expiresAt: runtime.now() + body.expires_in * 1000,
        scopes: body.scope ? body.scope.split(' ').filter(Boolean) : previous.scopes,
        loginId: previous.loginId ?? randomUUID(),
    }
}

async function refresh(runtime: Runtime, credential: OAuthCredential): Promise<OAuthCredential> {
    const response = await oauthPost(runtime, credential.host, 'oauth/token/', {
        grant_type: 'refresh_token',
        refresh_token: credential.refreshToken,
        client_id: HOG_CLIENT_ID,
    })
    const body = (response.json ?? {}) as TokenResponse & { error?: string }
    if (response.ok) {
        return credentialFromTokens(runtime, body, credential)
    }
    if (body.error === 'invalid_grant') {
        throw new HogError(
            'session_expired',
            'Your hog login expired or was revoked.',
            'Run `hog auth login` to log in again.'
        )
    }
    throw new HogError(
        'refresh_failed',
        `PostHog didn't renew your login: it answered with HTTP ${response.status}.`,
        'Run the command again. If it keeps failing, run `hog auth login`.'
    )
}

interface LockContents {
    id?: string
    createdAt?: number
}

async function readLock(runtime: Runtime, lock: string): Promise<LockContents | undefined> {
    try {
        return JSON.parse(await runtime.readFile(lock)) as LockContents
    } catch {
        return undefined
    }
}

async function withRefreshLock<T>(runtime: Runtime, host: string, work: () => Promise<T>): Promise<T> {
    const name = createHash('sha256').update(host).digest('hex').slice(0, 16)
    const lock = hogFile(runtime, `refresh-${name}.lock`)
    const id = randomUUID()
    // A lock that can't be read yet may be one another process is still writing, so its age counts
    // from when this process first saw it.
    let unreadableSince: number | undefined
    for (;;) {
        if (await runtime.createFile(lock, JSON.stringify({ id, createdAt: runtime.now() }))) {
            break
        }
        const contents = await readLock(runtime, lock)
        let createdAt: number
        if (contents?.createdAt === undefined) {
            unreadableSince ??= runtime.now()
            createdAt = unreadableSince
        } else {
            unreadableSince = undefined
            createdAt = contents.createdAt
        }
        if (runtime.now() - createdAt > LOCK_STALE_MS) {
            // Another process may have taken the stale lock over since the read above. Removing only
            // the lock this process judged stale keeps it from removing that process's live lock.
            if ((await readLock(runtime, lock))?.id === contents?.id) {
                await runtime.removeFile(lock)
            }
            unreadableSince = undefined
            continue
        }
        await runtime.sleep(LOCK_POLL_MS)
    }
    try {
        return await work()
    } finally {
        // A process that took over this lock as stale owns it now, so leave its lock in place.
        if ((await readLock(runtime, lock))?.id === id) {
            await runtime.removeFile(lock)
        }
    }
}

// An access token with time left. When PostHog rotates refresh tokens, it revokes the whole login if
// a rotated refresh token is used again, so two hog processes must never refresh at once: the
// refresh runs under a lock file, and re-reads the store inside it to pick up a token another
// process just stored.
export async function freshOAuthCredential(
    runtime: Runtime,
    store: KeychainStore | FileStore,
    credential: OAuthCredential
): Promise<OAuthCredential> {
    if (credential.expiresAt - runtime.now() > REFRESH_MARGIN_MS) {
        return credential
    }
    return withRefreshLock(runtime, credential.host, async () => {
        const current = (await readLogin(runtime, await readSettings(runtime), credential.host))?.credential
        if (current?.type !== 'oauth') {
            throw new HogError('not_authenticated', 'You logged out of hog.', 'Run `hog auth login` to log in again.')
        }
        if (current.expiresAt - runtime.now() > REFRESH_MARGIN_MS) {
            return current
        }
        const renewed = await refresh(runtime, current)
        await writeLogin(runtime, store, renewed)
        return renewed
    })
}
