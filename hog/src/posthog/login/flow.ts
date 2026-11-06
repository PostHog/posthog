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

import { writeLogin } from './stored'

export const LOGIN_COMMAND = 'hog auth login'

export interface LoggedIn {
    host: Host
    projectId: ProjectId
    store: StoreChoice
    // Set when the credentials are in a file.
    credentialsPath: string | null
    // Why hog couldn't use the keychain, when it stored the credentials in a file.
    keychainError: string | null
    status: AccessKeyStatus
}

// What `hog auth login --wait` needs to finish the login a previous run started.
export function loginWait(runtime: Runtime): ApprovalWait<PendingLogin, OAuthLogin> {
    return {
        command: LOGIN_COMMAND,
        noun: 'login',
        pending: PendingLoginSchema,
        poll: (pending, timeoutMs) => pollDeviceLogin(runtime, pending, timeoutMs),
    }
}

// An agent that retries `hog auth login` for the same host gets the same code back, so the link it
// already shared keeps working.
export function loginFlow(
    runtime: Runtime,
    host: Host,
    scopes: readonly string[]
): ApprovalFlow<PendingLogin, OAuthLogin> {
    return {
        ...loginWait(runtime),
        start: () => startDeviceLogin(runtime, host, scopes),
        reuse: (existing) => existing.host === host && existing.scopes.join(' ') === scopes.join(' '),
    }
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
    // Under the renewal lock, so a renewal of the previous login that is still in flight can't
    // store that login over this one.
    await withLoginLock(runtime, host, async () => {
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
    })
    await clearPending(runtime, LOGIN_COMMAND)
    return {
        host,
        projectId,
        store: store.kind,
        credentialsPath: store.path,
        keychainError,
        status: key.status(),
    }
}
