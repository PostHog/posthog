import posthog from 'posthog-js'

import api from 'lib/api'
import { chunk } from 'lib/utils/arrays'

import { FileSystemEntry } from '~/queries/schema/schema-general'
import { ProjectTreeRef } from '~/types'

// One request per ref, so chunk rather than firing a full page of them at once.
const BATCH_SIZE = 10
// A ref can carry several shortcuts alongside the row itself; fetch enough to look past them.
const ROWS_PER_REF = 10

async function resolveOne({ type, ref }: ProjectTreeRef): Promise<FileSystemEntry | null> {
    if (!ref) {
        return null
    }
    try {
        // A trailing slash means `type` is a prefix covering several internal types — see `ProjectTreeRef`.
        const response = await api.fileSystem.list(
            type.endsWith('/')
                ? { type__startswith: type, ref, limit: ROWS_PER_REF }
                : { type, ref, limit: ROWS_PER_REF }
        )
        // A shortcut shares the ref of the row it points at; moving it would leave the object where it was.
        return response.results.find((entry) => !entry.shortcut) ?? null
    } catch (error) {
        // Callers run this from async listeners rather than kea-loaders, so initKea's global onFailure
        // never sees it.
        posthog.captureException(error)
        return null
    }
}

/**
 * Look up the file system rows for objects a caller only knows by project-tree ref. Refs that resolve to
 * nothing are dropped, so the result can be shorter than the input; callers decide how to report that.
 */
export async function resolveProjectTreeRefs(refs: ProjectTreeRef[]): Promise<FileSystemEntry[]> {
    const entries: FileSystemEntry[] = []
    for (const batch of chunk(refs, BATCH_SIZE)) {
        const resolved = await Promise.all(batch.map(resolveOne))
        entries.push(...resolved.filter((entry): entry is FileSystemEntry => !!entry))
    }
    return entries
}
