import { HogError } from '@/core/errors'
import type { Runtime } from '@/core/runtime'
import { PersonalAPIKey, type AccessKey } from '@/posthog/access-key'
import { FileStore } from '@/posthog/credential-store/file'
import { probeKeychain } from '@/posthog/credential-store/keychain'
import { openStore } from '@/posthog/credential-store/open'
import type { StoreChoice } from '@/posthog/credential-store/types'
import { posthogFile } from '@/posthog/credentials'
import { startDeviceLogin, waitForApproval, type PendingLogin } from '@/posthog/device-auth'
import { loginFor, readSettings } from '@/posthog/settings'

import { writeLogin } from './stored'

const PENDING_LOGIN_FILE = 'login-pending.json'

// Reusing a code this close to expiry would hand the person a link that dies while they open it.
const REUSE_MARGIN_MS = 60_000

export interface LoggedIn {
    host: string
    projectId: string
    store: StoreChoice
    // Set when the credentials are in a file.
    credentialsPath: string | null
    // Why hog couldn't use the keychain, when it stored the credentials in a file.
    keychainError: string | null
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
    const { projectId, apiKey, scopes } = approval
    const key = new PersonalAPIKey({ host: pending.host, projectId, apiKey, scopes })
    const loggedIn = await saveLogin(runtime, key)
    return { ...loggedIn, scopes: approval.scopes }
}

// Each login probes the keychain again, so a login at the desk moves credentials out of the file a
// login over SSH had to use. Clears any pending login too, so a later `--wait` can't replace these
// credentials with an older approval.
export async function saveLogin(runtime: Runtime, unverified: AccessKey): Promise<LoggedIn> {
    const key = await unverified.verify(runtime)
    const [probe, previous] = await Promise.all([probeKeychain(runtime), readSettings(runtime)])
    let store = openStore(runtime, probe.usable ? 'keychain' : 'file')
    let keychainError = probe.usable ? null : probe.reason
    const { host, projectId } = key
    try {
        // A keychain that times out sends the login to the file below.
        await writeLogin(runtime, store, key, { lastLogin: true, removeIfLate: true })
    } catch (error) {
        // The probe writes an item of its own, so the keychain can still refuse this host's item,
        // such as one an older hog build saved.
        if (store.kind !== 'keychain' || !(error instanceof HogError) || !error.code.startsWith('keychain_')) {
            throw error
        }
        keychainError = error.message
        store = new FileStore(runtime)
        await writeLogin(runtime, store, key, { lastLogin: true })
    }
    // Only an old file login is removed. Removing a keychain login after a failed probe would wait for the keychain again.
    if (loginFor(previous, host)?.store === 'file' && store.kind === 'keychain') {
        await new FileStore(runtime).remove(host)
    }
    await clearPendingLogin(runtime)
    return {
        host,
        projectId,
        store: store.kind,
        credentialsPath: store.path,
        keychainError,
        scopes: [],
    }
}
