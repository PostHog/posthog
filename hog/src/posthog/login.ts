import { HogError } from '@/core/errors'
import type { Runtime } from '@/core/runtime'

import { posthogFile, saveCredentials, type Credentials } from './credentials'
import { startDeviceLogin, waitForApproval, type PendingLogin } from './device-auth'

const PENDING_LOGIN_FILE = 'login-pending.json'

// Reusing a code this close to expiry would hand the person a link that dies while they open it.
const REUSE_MARGIN_MS = 60_000

export interface LoggedIn {
    host: string
    projectId: string
    credentialsPath: string
    scopes: string[]
}

export async function readPendingLogin(runtime: Runtime): Promise<PendingLogin | undefined> {
    try {
        return JSON.parse(await runtime.readFile(posthogFile(runtime, PENDING_LOGIN_FILE))) as PendingLogin
    } catch {
        return undefined
    }
}

export async function clearPendingLogin(runtime: Runtime): Promise<void> {
    await runtime.removeFile(posthogFile(runtime, PENDING_LOGIN_FILE))
}

// Retrying agents get the same code back, so the link they already shared keeps working.
export async function startLogin(runtime: Runtime, host: string): Promise<PendingLogin> {
    const existing = await readPendingLogin(runtime)
    const pending =
        existing?.host === host && existing.expiresAt - runtime.now() > REUSE_MARGIN_MS
            ? existing
            : await startDeviceLogin(runtime, host)
    await runtime.writePrivateFile(posthogFile(runtime, PENDING_LOGIN_FILE), JSON.stringify(pending))
    return pending
}

// Waits for the person to approve, then saves the key. A login that can't succeed any more is
// forgotten. One that lost contact with PostHog stays, so `hog auth login --wait` can resume it.
export async function completeLogin(runtime: Runtime, pending: PendingLogin): Promise<LoggedIn> {
    let approval
    try {
        approval = await waitForApproval(runtime, pending)
    } catch (error) {
        if (error instanceof HogError && error.code !== 'login_interrupted') {
            await clearPendingLogin(runtime)
        }
        throw error
    }
    const loggedIn = await saveLogin(runtime, { ...approval, host: pending.host })
    return { ...loggedIn, scopes: approval.scopes }
}

// Clears any pending login too, so a later `--wait` can't replace these credentials with an older approval.
export async function saveLogin(runtime: Runtime, credentials: Credentials): Promise<LoggedIn> {
    const credentialsPath = await saveCredentials(runtime, credentials)
    await clearPendingLogin(runtime)
    return { host: credentials.host, projectId: credentials.projectId, credentialsPath, scopes: [] }
}
