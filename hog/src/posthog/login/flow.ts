import { clearPending, type ApprovalFlow, type ApprovalWait } from '@/core/approval'
import { HogError } from '@/core/errors'
import type { Runtime } from '@/core/runtime'
import type { AccessKey, AccessKeyStatus } from '@/posthog/access-key'
import { FileStore } from '@/posthog/credential-store/file'
import { probeKeychain } from '@/posthog/credential-store/keychain'
import { openStore } from '@/posthog/credential-store/open'
import type { StoreChoice } from '@/posthog/credential-store/types'
import { pollDeviceLogin, PendingLoginSchema, startDeviceLogin, type PendingLogin } from '@/posthog/device-auth'
import type { Host } from '@/posthog/host'
import type { ProjectId } from '@/posthog/ids'
import { withLoginLock, type OAuthLogin } from '@/posthog/oauth'
import { loginFor, readSettings } from '@/posthog/settings'

import { readLogin, writeLogin } from './stored'

export const LOGIN_COMMAND = 'hog auth login'
// Step-up: a new login with the scopes the current one has plus new ones.
export const ADD_COMMAND = 'hog auth add'
// Every command that ends in a device login, so logout can drop their pending approvals.
export const LOGIN_COMMANDS = [LOGIN_COMMAND, ADD_COMMAND]

export interface LoggedIn {
    host: Host
    projectId: ProjectId
    store: StoreChoice
    // Set when the credentials are in a file.
    credentialsPath: string | null
    // Why hog couldn't use the keychain, when it stored the credentials in a file.
    keychainError: string | null
    status: AccessKeyStatus
    // The project of the login this one replaced, when the person picked another one. Null otherwise.
    previousProjectId: ProjectId | null
}

// What `<command> --wait` needs to finish the login a previous run of `command` started.
export function loginWait(runtime: Runtime, command = LOGIN_COMMAND): ApprovalWait<PendingLogin, OAuthLogin> {
    return {
        command,
        noun: 'login',
        pending: PendingLoginSchema,
        poll: (pending, timeoutMs) => pollDeviceLogin(runtime, pending, timeoutMs, command),
    }
}

// An agent that retries the command for the same host and scopes gets the same code back, so the
// link it already shared keeps working.
export function loginFlow(
    runtime: Runtime,
    host: Host,
    scopes: readonly string[],
    { command = LOGIN_COMMAND, requiredScopes = [] }: { command?: string; requiredScopes?: readonly string[] } = {}
): ApprovalFlow<PendingLogin, OAuthLogin> {
    return {
        ...loginWait(runtime, command),
        start: () => startDeviceLogin(runtime, host, { scopes, requiredScopes, command }),
        reuse: (existing) =>
            existing.host === host &&
            existing.scopes.join(' ') === scopes.join(' ') &&
            existing.requiredScopes.join(' ') === requiredScopes.join(' '),
    }
}

// Each login probes the keychain again, so a login at the desk moves credentials out of the file a
// login over SSH had to use. Clears every pending login too, so a later `--wait` of any login
// command can't replace these credentials with an older approval.
// `replace` is for a step-up. It gets the stored login and returns the key to save in its place.
// The stored login is revoked once the new one is saved, so it doesn't linger in PostHog.
export async function saveLogin(
    runtime: Runtime,
    unverified: AccessKey,
    { replace }: { replace?: (stored: AccessKey) => AccessKey } = {}
): Promise<LoggedIn> {
    let key = await unverified.verify(runtime)
    const [probe, previous] = await Promise.all([probeKeychain(runtime), readSettings(runtime)])
    let store = openStore(runtime, probe.usable ? 'keychain' : 'file')
    let keychainError = probe.usable ? null : probe.reason
    let previousProjectId: ProjectId | null = null
    const { host } = key
    // Under the renewal lock, so a renewal of the previous login that is still in flight can't
    // store that login over this one.
    const replaced = await withLoginLock(runtime, host, async () => {
        // Read inside the lock, so the login revoked below is the one this replaces, not one a
        // renewal already rotated.
        const stored = replace && (await readLogin(runtime, await readSettings(runtime), host))?.key
        if (stored) {
            key = replace(stored)
            previousProjectId = stored.projectId === key.projectId ? null : stored.projectId
        }
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
            // The failed keychain write can still land after hog gave up on it.
            await writeLogin(runtime, store, key, { lastLogin: true, keychainLeftover: true })
        }
        // Only an old file login is removed. Removing a keychain login after a failed probe would wait for the keychain again.
        if (loginFor(previous, host)?.store === 'file' && store.kind === 'keychain') {
            await new FileStore(runtime).remove(host)
        }
        return stored || undefined
    })
    // Outside the lock: once the new login is stored, no renewal can rotate the replaced one. A
    // failed revoke leaves the replaced login working until it expires, which is no reason to fail a
    // step-up that already saved its tokens.
    await Promise.all([replaced?.logout(runtime), ...LOGIN_COMMANDS.map((command) => clearPending(runtime, command))])
    return {
        host,
        projectId: key.projectId,
        store: store.kind,
        credentialsPath: store.path,
        keychainError,
        status: key.status(),
        previousProjectId,
    }
}
