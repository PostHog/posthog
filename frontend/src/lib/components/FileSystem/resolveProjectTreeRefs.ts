import posthog from 'posthog-js'

import api from 'lib/api'
import { chunk } from 'lib/utils/arrays'

import { FileSystemEntry } from '~/queries/schema/schema-general'
import { ProjectTreeRef } from '~/types'

// Refs per request. The whole selection in one call would be unbounded, and the row cap below
// multiplies against it.
const BATCH_SIZE = 50
// shortcut is nullable, so the API's ordering does not reliably put the real row first; scan a few.
const ROWS_PER_REF = 10

async function resolveBatch(type: string, refs: string[]): Promise<FileSystemEntry[]> {
    try {
        // A trailing slash means `type` is a prefix covering several internal types — see `ProjectTreeRef`.
        const typeFilter = type.endsWith('/') ? { type__startswith: type } : { type }
        const response = await api.fileSystem.list({
            ...typeFilter,
            refs,
            limit: refs.length * ROWS_PER_REF,
        })
        return response.results
    } catch (error) {
        // Callers run this from async listeners rather than kea-loaders, so initKea's global onFailure
        // never sees it.
        posthog.captureException(error, { refs, type })
        return []
    }
}

/**
 * Look up the file system rows for objects a caller only knows by project-tree ref. Refs that resolve to
 * nothing are dropped, so the result can be shorter than the input; callers decide how to report that.
 */
export async function resolveProjectTreeRefs(refs: ProjectTreeRef[]): Promise<FileSystemEntry[]> {
    const wanted = refs.filter((ref): ref is ProjectTreeRef & { ref: string } => !!ref.ref)
    const byType = new Map<string, string[]>()
    for (const { type, ref } of wanted) {
        byType.set(type, [...(byType.get(type) ?? []), ref])
    }

    // Keyed on the requested type, not the row's own: a prefix query returns rows whose type is the
    // full internal one, and two types can share a ref value.
    // Batches run together, so wall-clock stays one round trip however large the selection is.
    const batches = [...byType].flatMap(([type, typeRefs]) =>
        chunk(typeRefs, BATCH_SIZE).map((batch) => ({ type, batch }))
    )
    const results = await Promise.all(batches.map(({ type, batch }) => resolveBatch(type, batch)))

    const found = new Map<string, FileSystemEntry>()
    results.forEach((entries, index) => {
        for (const entry of entries) {
            const key = `${batches[index].type}::${entry.ref}`
            // A shortcut shares the ref of the row it points at; moving it would leave the object where it was.
            if (entry.ref && !entry.shortcut && !found.has(key)) {
                found.set(key, entry)
            }
        }
    })

    return wanted
        .map(({ type, ref }) => found.get(`${type}::${ref}`))
        .filter((entry): entry is FileSystemEntry => !!entry)
}
