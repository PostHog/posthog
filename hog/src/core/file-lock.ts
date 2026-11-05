import { randomUUID } from 'node:crypto'

import { hogFile } from './paths'
import type { Runtime } from './runtime'

// A lock older than this belongs to a process that died before it removed it. The owner rewrites
// its lock every LOCK_REFRESH_MS while it works, so waiting on another lock or on a keychain dialog
// never makes a live lock look abandoned.
const LOCK_STALE_MS = 180_000
const LOCK_REFRESH_MS = 60_000
const LOCK_POLL_MS = 250

interface LockContents {
    id?: string
    createdAt?: number
}

async function readLock(runtime: Runtime, lock: string): Promise<LockContents | undefined> {
    try {
        return JSON.parse(await runtime.readFile(lock)) as LockContents
    } catch {
        return undefined
    }
}

function lockContents(runtime: Runtime, id: string): string {
    return JSON.stringify({ id, createdAt: runtime.now() })
}

async function lockHasId(runtime: Runtime, lock: string, id: string | undefined): Promise<boolean> {
    return (await readLock(runtime, lock))?.id === id
}

// Removes the lock only while it still has `id`, so a lock another process took over stays.
async function releaseLock(runtime: Runtime, lock: string, id: string | undefined): Promise<void> {
    if (await lockHasId(runtime, lock, id)) {
        await runtime.removeFile(lock)
    }
}

async function acquireLock(runtime: Runtime, lock: string, id: string): Promise<void> {
    // A lock that can't be read yet may be one another process is still writing, so its age counts
    // from when this process first saw it.
    let unreadableSince: number | undefined
    while (!(await runtime.createFile(lock, lockContents(runtime, id)))) {
        const contents = await readLock(runtime, lock)
        if (contents?.createdAt !== undefined) {
            unreadableSince = undefined
        }
        const createdAt = contents?.createdAt ?? (unreadableSince ??= runtime.now())
        if (runtime.now() - createdAt <= LOCK_STALE_MS) {
            await runtime.sleep(LOCK_POLL_MS)
            continue
        }
        // Another process may have taken the stale lock over since the read above. Removing only
        // the lock this process judged stale keeps it from removing that process's live lock.
        await releaseLock(runtime, lock, contents?.id)
        unreadableSince = undefined
    }
}

async function keepLockFresh(runtime: Runtime, lock: string, id: string, signal: AbortSignal): Promise<void> {
    try {
        for (;;) {
            await runtime.sleep(LOCK_REFRESH_MS, signal)
            if (signal.aborted || !(await lockHasId(runtime, lock, id))) {
                return
            }
            await runtime.writePrivateFile(lock, lockContents(runtime, id))
        }
    } catch {
        // A failed refresh only stops the refreshing. The lock may then look abandoned after
        // LOCK_STALE_MS, which is the behavior without refreshing, and the work keeps going.
    }
}

// Each hog process that reaches the same lock waits for the one before it.
export async function withFileLock<T>(runtime: Runtime, name: string, work: () => Promise<T>): Promise<T> {
    const lock = hogFile(runtime, name)
    const id = randomUUID()
    await acquireLock(runtime, lock, id)
    const done = new AbortController()
    const refreshing = keepLockFresh(runtime, lock, id, done.signal)
    try {
        return await work()
    } finally {
        done.abort()
        await refreshing
        await releaseLock(runtime, lock, id)
    }
}
