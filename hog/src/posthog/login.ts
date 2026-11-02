import { clearPending, type ApprovalFlow } from '@/core/approval'
import type { Runtime } from '@/core/runtime'

import type { Credential } from './credential'
import { FileStore, openStore, probeKeychain, type StoreChoice } from './credential-store'
import { pollDeviceLogin, startDeviceLogin, type Approval, type PendingLogin } from './device-auth'
import { writeLogin } from './logins'
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
}

// An agent that retries `hog auth login` for the same host gets the same code back, so the link it
// already shared keeps working. `host` is only needed to start a new login.
export function loginFlow(runtime: Runtime, host?: string): ApprovalFlow<PendingLogin, Approval> {
    return {
        command: LOGIN_COMMAND,
        noun: 'login',
        start: () => {
            if (host === undefined) {
                throw new Error('A new login needs a host')
            }
            return startDeviceLogin(runtime, host)
        },
        reuse: (existing) => existing.host === host,
        poll: (pending, timeoutMs) => pollDeviceLogin(runtime, pending, timeoutMs),
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
    return {
        host,
        projectId,
        store: store.kind,
        credentialsPath: store instanceof FileStore ? store.path : null,
        keychainProblem: probe.usable ? null : probe.reason,
        scopes: [],
    }
}
