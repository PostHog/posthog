import { HogError } from '@/core/errors'
import { withFileLock } from '@/core/file-lock'
import type { Runtime } from '@/core/runtime'
import { accessKeyFromStorage, type AccessKey, type AccessKeyStorage, type LogoutOutcome } from '@/posthog/access-key'
import { FileStore } from '@/posthog/credential-store/file'
import {
    hostItemName,
    itemName,
    ownerItemName,
    type ItemName,
    type ItemOwner,
    type LoginTarget,
} from '@/posthog/credential-store/item-name'
import { KeychainStore } from '@/posthog/credential-store/keychain'
import { openStore } from '@/posthog/credential-store/open'
import type { StoreChoice } from '@/posthog/credential-store/types'
import { sameHost, type Host } from '@/posthog/host'
import { withLoginLock } from '@/posthog/oauth'
import {
    loginFor,
    loginsFor,
    readSettings,
    recordItemName,
    withLogin,
    writeSettings,
    type HogSettings,
    type LoginRecord,
} from '@/posthog/settings'

// settings.json and the credentials file hold every login, so each write reads them, changes one
// entry and writes them back. The lock keeps two hog processes from dropping each other's entry.
const LOGINS_LOCK = 'logins.lock'

export interface LoggedOut extends LogoutOutcome {
    // Why hog couldn't remove the keychain item a file login left behind. Null when there was none.
    keychainLeftover: string | null
}

// A null `projectId` is a secret filed under its host alone that settings.json no longer named.
export type LoggedOutLogin = LoggedOut & ItemOwner

export interface StoredLogin {
    key: AccessKey
    store: KeychainStore | FileStore
}

export async function readLogin(
    runtime: Runtime,
    settings: HogSettings,
    target: LoginTarget
): Promise<StoredLogin | undefined> {
    const record = loginFor(settings, target)
    if (!record) {
        return undefined
    }
    const store = openStore(runtime, record.store)
    const secret = await store.read(recordItemName(record))
    const key = secret && accessKeyFromStorage(record, secret)
    return key ? { key, store } : undefined
}

export function loginStorage(runtime: Runtime, login: StoredLogin): AccessKeyStorage {
    const { host, projectId } = login.key
    const target = { host, projectId }
    return {
        reread: async () => (await readLogin(runtime, await readSettings(runtime), target))?.key,
        // A step-up can move the login to another store while this command runs, so a renewal saves
        // where settings.json says the login is now.
        save: async (key) => {
            const record = loginFor(await readSettings(runtime), target)
            await writeLogin(runtime, record ? openStore(runtime, record.store) : login.store, key)
        },
    }
}

// Writes the secrets first, so settings.json never names a login whose secrets aren't stored yet.
// The settings are read again just before the write, so a change another hog process made to a
// different login survives. `lastLogin` is for a new login, which becomes the one commands use when
// nothing names a project.
export async function writeLogin(
    runtime: Runtime,
    store: KeychainStore | FileStore,
    key: AccessKey,
    options: { lastLogin?: boolean; removeIfLate?: boolean; keychainLeftover?: boolean } = {}
): Promise<void> {
    const name = itemName(key)
    await withFileLock(runtime, LOGINS_LOCK, async () => {
        await store.write(name, key.secret(), { removeIfLate: options.removeIfLate })
        const current = await readSettings(runtime)
        const previous = loginFor(current, key)
        const keychainLeftover =
            store.kind === 'file' &&
            (options.keychainLeftover === true || previous?.store === 'keychain' || previous?.keychainLeftover === true)
        const loggedInAt = options.lastLogin ? runtime.now() : previous?.loggedInAt
        const record: LoginRecord = {
            ...key.record(store.kind),
            ...(keychainLeftover ? { keychainLeftover } : {}),
            ...(loggedInAt === undefined ? {} : { loggedInAt }),
        }
        const settings = withLogin(current, key, record)
        await writeSettings(runtime, options.lastLogin ? { ...settings, host: key.host } : settings)
        // The previous secrets go only once settings.json no longer names them. A failed removal leaves
        // them to `hog auth logout --all` instead of failing a login that is already saved. A keychain
        // item stays when the login moved to the file, because the keychain just failed and hog would
        // wait for it again. `keychainLeftover` marks it for logout instead.
        const stale: { store: StoreChoice; name: ItemName }[] = []
        if (previous && !(previous.store === 'keychain' && store.kind === 'file')) {
            const previousName = recordItemName(previous)
            if (previous.store !== store.kind || previousName !== name) {
                stale.push({ store: previous.store, name: previousName })
            }
        }
        // The write above replaced a leftover under the login's own name, but not one under the host.
        if (previous?.keychainLeftover && store.kind === 'keychain' && !hostItemInUse(settings, key.host)) {
            stale.push({ store: 'keychain', name: hostItemName(key.host) })
        }
        for (const item of stale) {
            await openStore(runtime, item.store)
                .remove(item.name)
                .catch(() => false)
        }
    })
}

function hostItemInUse(settings: HogSettings, host: Host): boolean {
    return loginsFor(settings, host).some((other) => other.storedUnderHost)
}

// Resolves to false when the store held nothing for the login.
async function removeLogin(runtime: Runtime, record: LoginRecord, store: KeychainStore | FileStore): Promise<boolean> {
    return withFileLock(runtime, LOGINS_LOCK, async () => {
        const removed = await store.remove(recordItemName(record))
        const settings = withLogin(await readSettings(runtime), record, undefined)
        // Commands fall back to the last login's host, so it stays while the host has other logins.
        const lastHostGone =
            settings.host !== undefined &&
            sameHost(settings.host, record.host) &&
            loginsFor(settings, record.host).length === 0
        await writeSettings(runtime, lastHostGone ? { logins: settings.logins } : settings)
        return removed
    })
}

// Logs this machine out of one login: the key revokes itself where it can, and hog removes its
// stored copy. Resolves to undefined when hog had no login to remove.
// Under the renewal lock, so a renewal in another hog process can neither restore the login after
// this removes it, nor rotate the refresh token this revokes.
export async function logout(runtime: Runtime, target: LoginTarget): Promise<LoggedOut | undefined> {
    return withLoginLock(runtime, target, async () => {
        const settings = await readSettings(runtime)
        const record = loginFor(settings, target)
        if (!record) {
            return undefined
        }
        const login = await readLogin(runtime, settings, target)
        if (!login) {
            // The store can hold an item hog can't read, such as a key an older hog accepted, and
            // the file entry can be gone while the record still names a keychain item left behind.
            // Both are removed, so logout leaves no secret behind.
            const removed = await removeLogin(runtime, record, openStore(runtime, record.store))
            if (!removed && !record.keychainLeftover) {
                return undefined
            }
            const leftover = record.keychainLeftover ? await removeKeychainLeftover(runtime, settings, record) : null
            // hog can't revoke an OAuth login it can't read, so logout says the session may still work.
            const revoked = record.type === 'oauth' ? false : null
            return { revoked, revokeUrl: null, keychainLeftover: leftover }
        }
        const [outcome, removed] = await Promise.all([
            login.key.logout(runtime),
            removeLogin(runtime, record, login.store),
        ])
        if (!removed) {
            return undefined
        }
        const leftover = record.keychainLeftover ? await removeKeychainLeftover(runtime, settings, record) : null
        return { ...outcome, keychainLeftover: leftover }
    })
}

// Resolves to why the removal failed, or null once no item is left. The keychain login a file login
// replaced can have kept its secret under the host alone, so that item goes too, unless another
// login still keeps its secret there.
async function removeKeychainLeftover(
    runtime: Runtime,
    settings: HogSettings,
    record: LoginRecord
): Promise<string | null> {
    const keychain = new KeychainStore(runtime)
    const names = hostItemInUse(withLogin(settings, record, undefined), record.host)
        ? [itemName(record)]
        : [itemName(record), hostItemName(record.host)]
    try {
        for (const name of names) {
            await keychain.remove(name)
        }
        return null
    } catch (error) {
        return error instanceof Error ? error.message : String(error)
    }
}

// For an item settings.json doesn't name. A machine without a usable keychain can't hold one, so
// only a refused or abandoned removal counts as a failure.
async function sweepKeychain(runtime: Runtime, name: ItemName): Promise<{ removed: boolean; error: string | null }> {
    try {
        return { removed: await new KeychainStore(runtime).remove(name), error: null }
    } catch (error) {
        if (error instanceof HogError && error.code === 'keychain_unavailable') {
            return { removed: false, error: null }
        }
        return { removed: false, error: error instanceof Error ? error.message : String(error) }
    }
}

// Logs this machine out of every login in settings.json or the credentials file. It also removes the
// entries of the credentials file and the keychain items that settings.json doesn't name, such as a
// keychain item from before settings.json was lost. Each host's own item is swept too, because it
// can hold a secret filed under the host alone.
export async function logoutAll(runtime: Runtime): Promise<LoggedOutLogin[]> {
    const settings = await readSettings(runtime)
    const file = new FileStore(runtime)
    const items = new Map<ItemName, ItemOwner>()
    const add = (owner: ItemOwner): void => {
        const name = ownerItemName(owner)
        if (!items.has(name)) {
            items.set(name, owner)
        }
    }
    for (const { host, projectId } of [...settings.logins, ...(await file.owners())]) {
        add({ host, projectId })
        add({ host, projectId: null })
    }
    const loggedOut: LoggedOutLogin[] = []
    for (const [name, owner] of items) {
        const { host, projectId } = owner
        const target = projectId === null ? undefined : { host, projectId }
        const record = target && loginFor(settings, target)
        const outcome = target && (await logout(runtime, target))
        const orphan = await withFileLock(runtime, LOGINS_LOCK, () => file.remove(name))
        // Logout already handled a keychain login and a marked leftover.
        const swept =
            record?.store !== 'keychain' && !record?.keychainLeftover
                ? await sweepKeychain(runtime, name)
                : { removed: false, error: null }
        if (outcome || orphan || swept.removed || swept.error) {
            const base = outcome ?? { revoked: null, revokeUrl: null, keychainLeftover: null }
            loggedOut.push({ ...base, keychainLeftover: base.keychainLeftover ?? swept.error, host, projectId })
        }
    }
    await withFileLock(runtime, LOGINS_LOCK, () => file.removeUnreadable())
    return loggedOut
}
