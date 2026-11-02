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

// Runs `work` while this process holds the lock file `name` in hog's folder. Each hog process that
// reaches the same lock waits for the one before it.
export async function withFileLock<T>(runtime: Runtime, name: string, work: () => Promise<T>): Promise<T> {
    const lock = hogFile(runtime, name)
    const id = randomUUID()
    // A lock that can't be read yet may be one another process is still writing, so its age counts
    // from when this process first saw it.
    let unreadableSince: number | undefined
    for (;;) {
        if (await runtime.createFile(lock, JSON.stringify({ id, createdAt: runtime.now() }))) {
            break
        }
        const contents = await readLock(runtime, lock)
        let createdAt: number
        if (contents?.createdAt === undefined) {
            unreadableSince ??= runtime.now()
            createdAt = unreadableSince
        } else {
            unreadableSince = undefined
            createdAt = contents.createdAt
        }
        if (runtime.now() - createdAt > LOCK_STALE_MS) {
            // Another process may have taken the stale lock over since the read above. Removing only
            // the lock this process judged stale keeps it from removing that process's live lock.
            if ((await readLock(runtime, lock))?.id === contents?.id) {
                await runtime.removeFile(lock)
            }
            unreadableSince = undefined
            continue
        }
        await runtime.sleep(LOCK_POLL_MS)
    }
    const done = new AbortController()
    const refreshing = (async () => {
        for (;;) {
            await runtime.sleep(LOCK_REFRESH_MS, done.signal)
            if (done.signal.aborted || (await readLock(runtime, lock))?.id !== id) {
                return
            }
            await runtime.writePrivateFile(lock, JSON.stringify({ id, createdAt: runtime.now() }))
        }
    })()
    try {
        return await work()
    } finally {
        done.abort()
        await refreshing
        // A process that took over this lock as stale owns it now, so leave its lock in place.
        if ((await readLock(runtime, lock))?.id === id) {
            await runtime.removeFile(lock)
        }
    }
}
