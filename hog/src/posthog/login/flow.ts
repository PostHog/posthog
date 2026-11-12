import {
    clearPendingFor,
    waitIdentity,
    type ApprovalFlow,
    type ApprovalIdentity,
    type ApprovalWait,
} from '@/core/approval'
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
import { stepUpCommand } from '@/posthog/scope-challenge'
import { readSettings } from '@/posthog/settings'

import { readLogin, writeLogin } from './stored'

export const LOGIN_COMMAND = 'hog auth login'
export const ADD_COMMAND = 'hog auth add'

// A login approved later must not replace a newer login, or one removed by logout, through `--wait`.
// Another command that starts logins, such as `hog setup next`, names its pending items after
// `hog auth login`, so this clears them too.
export async function clearPendingLogins(runtime: Runtime): Promise<void> {
    await Promise.all([LOGIN_COMMAND, ADD_COMMAND].map((command) => clearPendingFor(runtime, command)))
}

export interface LoggedIn {
    host: Host
    projectId: ProjectId
    store: StoreChoice
    // Set when the credentials are in a file.
    credentialsPath: string | null
    // Why hog couldn't use the keychain, when it stored the credentials in a file.
    keychainError: string | null
    status: AccessKeyStatus
    replacedRevoked: boolean | null
}

function sameScopes(a: readonly string[], b: readonly string[]): boolean {
    return [...a].sort().join(' ') === [...b].sort().join(' ')
}

// What resuming needs to finish the login a previous run of `identity.command` started.
export function loginWait(
    runtime: Runtime,
    identity: ApprovalIdentity = waitIdentity(LOGIN_COMMAND)
): ApprovalWait<PendingLogin, OAuthLogin> {
    const { command } = identity

    return {
        ...identity,
        noun: 'login',
        pending: PendingLoginSchema,
        // `hog auth add` with no scopes is a usage error, so starting over has to name them.
        restart: (pending) =>
            pending.requiredScopes.length > 0 ? stepUpCommand(pending.requiredScopes, pending.host) : command,
        poll: (pending, timeoutMs) => pollDeviceLogin(runtime, pending, timeoutMs, command),
    }
}

// An agent that retries the command for the same host and scopes gets the same code back, so the
// link it already shared keeps working.
export function loginFlow(
    runtime: Runtime,
    host: Host,
    scopes: readonly string[],
    {
        identity = waitIdentity(LOGIN_COMMAND),
        requiredScopes = [],
        projectId,
    }: { identity?: ApprovalIdentity; requiredScopes?: readonly string[]; projectId?: ProjectId } = {}
): ApprovalFlow<PendingLogin, OAuthLogin> {
    const { command } = identity

    return {
        ...loginWait(runtime, identity),
        start: () => startDeviceLogin(runtime, host, { scopes, requiredScopes, command, projectId }),
        reuse: (existing) =>
            existing.host === host &&
            existing.projectId === projectId &&
            sameScopes(existing.scopes, scopes) &&
            sameScopes(existing.requiredScopes, requiredScopes),
    }
}

// Each login probes the keychain again, so a login at the desk moves credentials out of the file a
// login over SSH had to use. Clears every pending login, so an older approval can't replace this one.
export async function saveLogin(
    runtime: Runtime,
    unverified: AccessKey,
    { replace }: { replace?: (stored: AccessKey) => AccessKey } = {}
): Promise<LoggedIn> {
    let key = await unverified.verify(runtime)
    const probe = await probeKeychain(runtime)
    let store = openStore(runtime, probe.usable ? 'keychain' : 'file')
    let keychainError = probe.usable ? null : probe.reason
    const target = { host: key.host, projectId: key.projectId }

    // Under the renewal lock, so a renewal of the previous login that is still in flight can't
    // store that login over this one.
    const replaced = await withLoginLock(runtime, target, async () => {
        // Inside the lock, so the revoke below hits the current login. A failed read keeps the new tokens.
        const stored =
            replace && (await readLogin(runtime, await readSettings(runtime), target).catch(() => undefined))?.key
        if (stored) {
            key = replace(stored)
        }

        try {
            // A keychain that times out sends the login to the file below.
            await writeLogin(runtime, store, key, { leftBehind: [] })
        } catch (error) {
            // The probe writes an item of its own, so the keychain can still refuse this login's item,
            // such as one an older hog build saved.
            if (store.kind !== 'keychain' || !(error instanceof HogError) || !error.code.startsWith('keychain_')) {
                throw error
            }

            keychainError = error.message
            store = new FileStore(runtime)
            // The failed keychain write can still land after hog gave up on it.
            const late = { store: 'keychain', host: key.host, projectId: key.projectId } as const
            await writeLogin(runtime, store, key, { leftBehind: [late] })
        }

        return stored || undefined
    })

    // Outside the lock: no renewal can rotate the replaced login once the new one is stored.
    const [revoked] = await Promise.all([replaced?.logout(runtime), clearPendingLogins(runtime)])

    return {
        host: key.host,
        projectId: key.projectId,
        store: store.kind,
        credentialsPath: store.path,
        keychainError,
        status: key.status(),
        replacedRevoked: revoked?.revoked ?? null,
    }
}
