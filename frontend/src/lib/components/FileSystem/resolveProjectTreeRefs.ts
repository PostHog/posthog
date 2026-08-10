import posthog from 'posthog-js'

import api from 'lib/api'

import { FileSystemEntry } from '~/queries/schema/schema-general'
import { ProjectTreeRef } from '~/types'

// Resolving a selection sends one request per ref, so chunk them rather than firing a burst of up to a
// full page of parallel requests when a list page acts on everything the user selected.
const BATCH_SIZE = 10

async function resolveOne({ type, ref }: ProjectTreeRef): Promise<FileSystemEntry | null> {
    if (!ref) {
        return null
    }
    try {
        const response = await api.fileSystem.list({ type, ref, limit: 10 })
        // Shortcuts share a ref with the row they point at, and moving one would move the shortcut instead
        // of the object itself.
        return response.results.find((entry) => !entry.shortcut) ?? null
    } catch (error) {
        // Callers run this from async listeners rather than kea-loaders, so initKea's global onFailure
        // never sees it.
        posthog.captureException(error)
        return null
    }
}

/**
 * Look up the file system rows for objects a caller only knows by project-tree ref.
 *
 * List pages hold ids, not file system entries, and the sidebar's in-memory store only holds what it has
 * lazily loaded — so anything that needs a real entry (moving, renaming) has to ask the file system for it.
 * Refs that resolve to nothing are dropped, so the result can be shorter than the input; callers decide how
 * to report that.
 */
export async function resolveProjectTreeRefs(refs: ProjectTreeRef[]): Promise<FileSystemEntry[]> {
    const entries: FileSystemEntry[] = []
    for (let index = 0; index < refs.length; index += BATCH_SIZE) {
        const batch = refs.slice(index, index + BATCH_SIZE)
        const resolved = await Promise.all(batch.map(resolveOne))
        entries.push(...resolved.filter((entry): entry is FileSystemEntry => !!entry))
    }
    return entries
}
