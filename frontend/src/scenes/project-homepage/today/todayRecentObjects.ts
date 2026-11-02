import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { baseObjectType, libraryObjectHref } from 'scenes/library/libraryUtils'

import { FileSystemEntry } from '~/queries/schema/schema-general'

function objectKey(entry: FileSystemEntry): string {
    const href = libraryObjectHref({ type: baseObjectType(entry.type), ref: entry.ref }) ?? libraryObjectHref(entry)
    if (!href) {
        return `${baseObjectType(entry.type)}:${entry.ref ?? entry.id}`
    }
    const destination = removeProjectIdIfPresent(href).split('#')[0]
    const queryStart = destination.indexOf('?')
    const pathname = queryStart === -1 ? destination : destination.slice(0, queryStart)
    const search = queryStart === -1 ? '' : destination.slice(queryStart)
    return `${pathname.replace(/\/+$/, '')}${search}`
}

/** Recently viewed objects for the home, without tasks, which are agent sessions rather than things people look at. */
export function recentObjectsForHome(recents: FileSystemEntry[], limit: number): FileSystemEntry[] {
    const seen = new Set<string>()
    return recents
        .filter((entry) => {
            if (libraryObjectHref(entry) === null || baseObjectType(entry.type) === 'task') {
                return false
            }
            const key = objectKey(entry)
            if (seen.has(key)) {
                return false
            }
            seen.add(key)
            return true
        })
        .slice(0, limit)
}

export type JumpBackObject = FileSystemEntry & { jumpBackReason: 'recent' | 'frequent' }

export function jumpBackObjectsForHome(
    recents: FileSystemEntry[],
    frequent: FileSystemEntry[],
    limit: number
): JumpBackObject[] {
    const recentObjects = recentObjectsForHome(recents, limit)
    const first = recentObjects.slice(0, 2)
    const seen = new Set(first.map(objectKey))
    const result: JumpBackObject[] = first.map((entry) => ({ ...entry, jumpBackReason: 'recent' }))
    for (const entry of recentObjectsForHome(frequent, frequent.length)) {
        if (!seen.has(objectKey(entry))) {
            seen.add(objectKey(entry))
            result.push({ ...entry, jumpBackReason: 'frequent' })
            if (result.length === first.length + 2) {
                break
            }
        }
    }
    for (const entry of recentObjects) {
        if (!seen.has(objectKey(entry))) {
            seen.add(objectKey(entry))
            result.push({ ...entry, jumpBackReason: 'recent' })
        }
    }
    return result.slice(0, limit)
}
