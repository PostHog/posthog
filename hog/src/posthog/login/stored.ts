import { HogError } from '@/core/errors'
import { withFileLock } from '@/core/file-lock'
import type { Runtime } from '@/core/runtime'
import { accessKeyFromStorage, type AccessKey, type AccessKeyStorage, type LogoutOutcome } from '@/posthog/access-key'
import { FileStore } from '@/posthog/credential-store/file'
import { itemName, parseItemName, type ItemName, type LoginTarget } from '@/posthog/credential-store/item-name'
import { KeychainStore } from '@/posthog/credential-store/keychain'
import { openStore } from '@/posthog/credential-store/open'
import type { StoreChoice } from '@/posthog/credential-store/types'
import { sameHost } from '@/posthog/host'
import type { ProjectId } from '@/posthog/ids'
import { withLoginLock } from '@/posthog/oauth'
import {
    itemOf,
    loginFor,
    readSettings,
    withLogin,
    writeSettings,
    type HogSettings,
    type LoginRecord,
    type StoredItem,
} from '@/posthog/settings'

// settings.json and the credentials file hold every login, so each write reads them, changes one
// entry and writes them back. The lock keeps two hog processes from dropping each other's entry.
const LOGINS_LOCK = 'logins.lock'

const STORES: readonly StoreChoice[] = ['keychain', 'file']

export interface LoggedOut extends LogoutOutcome {
    // Why hog couldn't remove an older keychain item of the login's host. Null when none is left.
    keychainLeftover: string | null
}

export type LoggedOutLogin = LoggedOut & LoginTarget<ProjectId | null>

export interface StoredLogin {
    key: AccessKey
    store: KeychainStore | FileStore
}

function errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : String(error)
}

// Moving a secret can open a keychain dialog, so each hog process tries once.
const moveTried = new WeakSet<Runtime>()

// Moves the secret of a login filed under its host alone to the login's own item. The caller holds
// LOGINS_LOCK. A secret that fails to move stays where it is and keeps working, and the next hog
// process tries again.
async function moveToOwnItem(runtime: Runtime, target: LoginTarget): Promise<LoginRecord | undefined> {
    const settings = await readSettings(runtime)
    const record = loginFor(settings, target)
    // Another hog process can have moved it while this one waited for the lock.
    if (!record?.storedUnderHost) {
        return record
    }

    const moved = await moveHostSecret(runtime, record)
    if (moved === record) {
        return record
    }

    const written = await writeSettings(runtime, {
        ...withLogin(settings, target, moved),
        pendingRemovals: [...settings.pendingRemovals, itemOf(record)],
    })
    // Removing a file entry never waits, and the keychain was just used if the secret was there.
    await removePending(runtime, written, ['file', record.store])

    return moved
}

async function moveHostSecret(runtime: Runtime, record: LoginRecord): Promise<LoginRecord> {
    const store = openStore(runtime, record.store)
    try {
        const secret = await store.read(itemName(record.host, null))
        if (secret) {
            await store.write(itemName(record.host, record.projectId), secret, { removeIfLate: true })
        }
    } catch {
        return record
    }

    const { storedUnderHost: _, ...moved } = record
    return moved
}

// The caller holds LOGINS_LOCK.
async function removePending(
    runtime: Runtime,
    settings: HogSettings,
    stores: readonly StoreChoice[]
): Promise<{ settings: HogSettings; failures: { item: StoredItem; error: string }[] }> {
    const kept: StoredItem[] = []
    const failures: { item: StoredItem; error: string }[] = []

    for (const item of settings.pendingRemovals) {
        if (!stores.includes(item.store)) {
            kept.push(item)
            continue
        }

        try {
            await openStore(runtime, item.store).remove(itemName(item.host, item.projectId))
        } catch (error) {
            kept.push(item)
            failures.push({ item, error: errorMessage(error) })
        }
    }

    if (kept.length === settings.pendingRemovals.length) {
        return { settings, failures }
    }
    return { settings: await writeSettings(runtime, { ...settings, pendingRemovals: kept }), failures }
}

export async function readLogin(
    runtime: Runtime,
    settings: HogSettings,
    target: LoginTarget
): Promise<StoredLogin | undefined> {
    let record = loginFor(settings, target)
    if (record?.storedUnderHost && !moveTried.has(runtime)) {
        moveTried.add(runtime)
        const unmoved = record
        // A home folder hog can't write to, such as a read-only mount, keeps the login readable where it is.
        record = await withFileLock(runtime, LOGINS_LOCK, () => moveToOwnItem(runtime, target)).catch(() => unmoved)
    }
    if (!record) {
        return undefined
    }

    const store = openStore(runtime, record.store)
    const { host, projectId } = itemOf(record)
    const secret = await store.read(itemName(host, projectId))

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
// different login survives. The item the login used before becomes a pending removal.
// Only `newLogin` removes what is pending, because a removal can wait on the keychain while this lock
// holds every other login's renewal. `leftBehind` names items a failed write can still create.
export async function writeLogin(
    runtime: Runtime,
    store: KeychainStore | FileStore,
    key: AccessKey,
    newLogin?: { leftBehind: StoredItem[] }
): Promise<void> {
    await withFileLock(runtime, LOGINS_LOCK, async () => {
        await store.write(itemName(key.host, key.projectId), key.secret(), { removeIfLate: newLogin !== undefined })

        const current = await readSettings(runtime)
        const previous = loginFor(current, key)
        const loggedInAt = newLogin ? runtime.now() : previous?.loggedInAt
        const record: LoginRecord = { ...key.record(store.kind), ...(loggedInAt === undefined ? {} : { loggedInAt }) }

        const settings = await writeSettings(runtime, {
            ...withLogin(current, key, record),
            pendingRemovals: [
                ...current.pendingRemovals,
                ...(previous ? [itemOf(previous)] : []),
                ...(newLogin?.leftBehind ?? []),
            ],
        })

        if (newLogin) {
            // A login saved to the file found the keychain unusable, so the keychain items wait.
            await removePending(runtime, settings, store.kind === 'file' ? ['file'] : STORES)
        }
    })
}

interface RemovedLogin {
    record: LoginRecord
    // Undefined when hog couldn't read the secret, so it can't revoke the login.
    key: AccessKey | undefined
    removed: boolean
}

// Removes a login's secret and its record. Under the renewal lock, so a renewal in another hog process
// can't restore the login after this removes it. The store can hold a secret hog can't read, such as
// a key an older hog accepted, and it goes too.
// A removal that fails once the secret is read revokes the login before it throws, because the
// secret can be gone already and a retry couldn't revoke it.
async function removeLogin(runtime: Runtime, target: LoginTarget): Promise<RemovedLogin | undefined> {
    let loaded: AccessKey | undefined

    try {
        return await withLoginLock(runtime, target, async () => {
            const settings = await readSettings(runtime)
            const record = loginFor(settings, target)
            if (!record) {
                return undefined
            }

            const login = await readLogin(runtime, settings, target)
            loaded = login?.key

            // Reading the login can have moved its secret, so the record comes from settings.json again.
            return withFileLock(runtime, LOGINS_LOCK, async () => {
                const current = await readSettings(runtime)
                const stored = loginFor(current, target) ?? record
                const { host, projectId } = itemOf(stored)
                const removed = await openStore(runtime, stored.store).remove(itemName(host, projectId))

                // A move that copied the secret to the login's own item but failed to save settings.json
                // leaves that copy behind, so it becomes a pending removal.
                const copy: StoredItem[] = stored.storedUnderHost
                    ? [{ store: stored.store, host: stored.host, projectId: stored.projectId }]
                    : []
                await writeSettings(runtime, {
                    ...withLogin(current, target, undefined),
                    pendingRemovals: [...current.pendingRemovals, ...copy],
                })

                return { record: stored, key: login?.key, removed }
            })
        })
    } catch (error) {
        await loaded?.logout(runtime).catch(() => undefined)
        throw error
    }
}

// A login that is gone from this machine can't be revoked later, so an error from `work` waits for
// the revokes already sent.
async function afterRevokes<T>(revokes: readonly Promise<unknown>[], work: () => Promise<T>): Promise<T> {
    try {
        return await work()
    } catch (error) {
        await Promise.allSettled(revokes)
        throw error
    }
}

// Outside the renewal lock: once the login is gone, no renewal can rotate the refresh token this revokes.
function revoke(runtime: Runtime, { record, key }: RemovedLogin): Promise<LogoutOutcome> {
    // hog can't revoke an OAuth login it can't read, so logout says the session may still work.
    return key?.logout(runtime) ?? Promise.resolve({ revoked: record.type === 'oauth' ? false : null, revokeUrl: null })
}

// Logs this machine out of one login: hog removes its stored copy and every pending removal it can,
// and the key revokes itself where it can. Resolves to undefined when hog had nothing to remove.
export async function logout(runtime: Runtime, target: LoginTarget): Promise<LoggedOut | undefined> {
    const removed = await removeLogin(runtime, target)
    if (!removed) {
        return undefined
    }

    const revoked = revoke(runtime, removed)
    const { hadPending, failures } = await afterRevokes([revoked], () =>
        withFileLock(runtime, LOGINS_LOCK, async () => {
            const settings = await readSettings(runtime)
            const hadPending = settings.pendingRemovals.some((item) => sameHost(item.host, target.host))
            return { hadPending, ...(await removePending(runtime, settings, STORES)) }
        })
    )
    const outcome = await revoked

    if (!removed.removed && !hadPending) {
        return undefined
    }

    const leftover = failures.find(({ item }) => item.store === 'keychain' && sameHost(item.host, target.host))
    return { ...outcome, keychainLeftover: leftover?.error ?? null }
}

interface Sweep {
    removed: boolean
    error: string | null
}

// For an item settings.json doesn't name. A machine without a usable keychain can't hold one, so
// only a refused or abandoned removal counts as a failure.
async function sweepKeychain(runtime: Runtime, name: ItemName): Promise<Sweep> {
    try {
        return { removed: await new KeychainStore(runtime).remove(name), error: null }
    } catch (error) {
        if (error instanceof HogError && error.code === 'keychain_unavailable') {
            return { removed: false, error: null }
        }
        return { removed: false, error: errorMessage(error) }
    }
}

// Logs this machine out of every login in settings.json, and removes every other secret hog knows
// of: the pending removals, and the entries of the credentials file, such as one from before
// settings.json was lost. The keychain can't list its items, so hog removes the ones it can name.
export async function logoutAll(runtime: Runtime): Promise<LoggedOutLogin[]> {
    const settings = await readSettings(runtime)
    const file = new FileStore(runtime)
    const known = [...settings.logins, ...settings.pendingRemovals, ...(await file.owners())]

    // A login whose secret didn't move from its host's item reads it from there, so host items go last.
    const owners = new Map<ItemName, LoginTarget<ProjectId | null>>()
    for (const { host, projectId } of [
        ...known.filter((owner) => owner.projectId !== null),
        ...known.filter((owner) => owner.projectId === null),
    ]) {
        const name = itemName(host, projectId)
        if (!owners.has(name)) {
            owners.set(name, { host, projectId })
        }
    }

    const steps: {
        name: ItemName
        owner: LoginTarget<ProjectId | null>
        revoked: Promise<LogoutOutcome> | undefined
        swept: Sweep
    }[] = []
    const revokes: Promise<LogoutOutcome>[] = []
    const fromFile = await afterRevokes(revokes, async () => {
        for (const [name, owner] of owners) {
            const { host, projectId } = owner
            const removed =
                projectId !== null && loginFor(settings, { host, projectId })
                    ? await removeLogin(runtime, { host, projectId })
                    : undefined
            const revoked = removed?.removed ? revoke(runtime, removed) : undefined
            if (revoked) {
                revokes.push(revoked)
            }

            // A keychain login filed under its host alone can have a copy under its own name.
            const swept =
                removed?.record.store === 'keychain' && !removed.record.storedUnderHost
                    ? { removed: false, error: null }
                    : await sweepKeychain(runtime, name)
            steps.push({ name, owner, revoked, swept })
        }

        const names = new Set<string>(owners.keys())
        return withFileLock(runtime, LOGINS_LOCK, async () => {
            const removed = await file.removeWhere((name) => names.has(name) || parseItemName(name) === undefined)
            const failed = new Set<string>(steps.flatMap((step) => (step.swept.error ? [step.name] : [])))

            const current = await readSettings(runtime)
            await writeSettings(runtime, {
                ...current,
                // Another hog process can have added an item after this one listed them, and it stays.
                pendingRemovals: current.pendingRemovals.filter((item) => {
                    const name = itemName(item.host, item.projectId)
                    return !names.has(name) || (item.store === 'keychain' && failed.has(name))
                }),
            })

            return new Set(removed)
        })
    })

    const outcomes = await Promise.all(steps.map(({ revoked }) => revoked))

    return steps.flatMap(({ name, owner, swept }, index) => {
        const outcome = outcomes[index]

        if (!outcome && !fromFile.has(name) && !swept.removed && !swept.error) {
            return []
        }

        return [{ ...(outcome ?? { revoked: null, revokeUrl: null }), keychainLeftover: swept.error, ...owner }]
    })
}
