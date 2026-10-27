import { baseObjectType, libraryObjectHref } from 'scenes/library/libraryUtils'

import { FileSystemEntry } from '~/queries/schema/schema-general'

/** Recently viewed objects for the home, without tasks, which are agent sessions rather than things people look at. */
export function recentObjectsForHome(recents: FileSystemEntry[], limit: number): FileSystemEntry[] {
    return recents
        .filter((entry) => libraryObjectHref(entry) !== null && baseObjectType(entry.type) !== 'task')
        .slice(0, limit)
}

export type JumpBackObject = FileSystemEntry & { jumpBackReason: 'recent' | 'frequent' }

function objectKey(entry: FileSystemEntry): string {
    return `${baseObjectType(entry.type)}:${entry.ref ?? entry.id}`
}

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
