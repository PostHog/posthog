import { clearPending, type ApprovalFlow, type ApprovalWait } from '@/core/approval'
import { HogError } from '@/core/errors'
import type { Runtime } from '@/core/runtime'

import type { Credential, CredentialStatus } from './credential'
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
    status: CredentialStatus
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
    const [probe, previous] = await Promise.all([probeKeychain(runtime), readSettings(runtime)])
    let store = openStore(runtime, probe.usable ? 'keychain' : 'file')
    let keychainProblem = probe.usable ? null : probe.reason
    const { host, projectId } = credential
    try {
        await writeLogin(runtime, store, credential, { lastLogin: true })
    } catch (error) {
        // The probe writes an item of its own, so the keychain can still refuse this host's item,
        // such as one an older hog build saved.
        if (store.kind !== 'keychain' || !(error instanceof HogError) || !error.code.startsWith('keychain_')) {
            throw error
        }
        keychainProblem = error.message
        store = new FileStore(runtime)
        await writeLogin(runtime, store, credential, { lastLogin: true })
    }
    // Only an old file login is removed. Removing a keychain login after a failed probe would wait for the keychain again.
    if (loginFor(previous, host)?.store === 'file' && store.kind === 'keychain') {
        await new FileStore(runtime).remove(host)
    }
    await clearPending(runtime, LOGIN_COMMAND)
    return {
        host,
        projectId,
        store: store.kind,
        credentialsPath: store.path,
        keychainProblem,
        status: credential.status(),
    }
}
