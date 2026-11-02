import { clearPending, type ApprovalFlow, type ApprovalWait } from '@/core/approval'
import type { Runtime } from '@/core/runtime'

import type { Credential } from './credential'
import { FileStore, openStore, probeKeychain, type StoreChoice } from './credential-store'
import { LOGIN_SCOPES, pollDeviceLogin, startDeviceLogin, type PendingLogin } from './device-auth'
import { writeLogin } from './logins'
import type { OAuthLogin } from './oauth'
import { loginFor, readSettings } from './settings'

export const LOGIN_COMMAND = 'hog auth login'

export interface LoggedIn {
    host: string
    projectId: string
    store: StoreChoice
    // Set when the credentials are in a file.
    credentialsPath: string | null
    // Why hog couldn't use the keychain, when it stored the credentials in a file.
    keychainProblem: string | null
    scopes: string[]
    // Epoch milliseconds, for an OAuth login.
    expiresAt: number | null
}

// What `hog auth login --wait` needs to finish the login a previous run started.
export function loginWait(runtime: Runtime): ApprovalWait<PendingLogin, OAuthLogin> {
    return {
        command: LOGIN_COMMAND,
        noun: 'login',
        poll: (pending, timeoutMs) => pollDeviceLogin(runtime, pending, timeoutMs),
    }
}

// An agent that retries `hog auth login` for the same host gets the same code back, so the link it
// already shared keeps working.
export function loginFlow(runtime: Runtime, host: string): ApprovalFlow<PendingLogin, OAuthLogin> {
    return {
        ...loginWait(runtime),
        start: () => startDeviceLogin(runtime, host, LOGIN_SCOPES),
        reuse: (existing) => existing.host === host && existing.scopes?.join(' ') === LOGIN_SCOPES.join(' '),
    }
}

// Each login probes the keychain again, so a login at the desk moves credentials out of the file a
// login over SSH had to use. Clears any pending login too, so a later `--wait` can't replace these
// credentials with an older approval.
export async function saveLogin(runtime: Runtime, credential: Credential): Promise<LoggedIn> {
    const probe = await probeKeychain(runtime)
    const store = openStore(runtime, probe.usable ? 'keychain' : 'file')
    const previous = await readSettings(runtime)
    const { host, projectId } = credential
    await writeLogin(runtime, store, credential, { lastLogin: true })
    // Only an old file login is removed. Removing a keychain login after a failed probe would wait for the keychain again.
    if (loginFor(previous, host)?.store === 'file' && store.kind === 'keychain') {
        await new FileStore(runtime).remove(host)
    }
    await clearPending(runtime, LOGIN_COMMAND)
    const status = credential.status()
    return {
        host,
        projectId,
        store: store.kind,
        credentialsPath: store instanceof FileStore ? store.path : null,
        keychainProblem: probe.usable ? null : probe.reason,
        scopes: status.scopes ?? [],
        expiresAt: status.expiresAt,
    }
}
